# Diagnostic Architecture — ArnaqueRadar
> Analyse experte — Data Architect | Mai 2026

---

## 1. Vue d'ensemble de la structure actuelle

```
Projet 1 - Bloc 1 - C1 a 5/          ← racine workspace
│
├── arnaqueradar/                      ← package principal
│   ├── 1_collecter.py                 ← scripts numérotés pédagogiques
│   ├── 2_nettoyer.py
│   ├── 3_enrichir.py
│   ├── 4_controler_qualite.py
│   ├── 5_importer.py
│   ├── 6_preparer_dataset_ml.py
│   ├── 7_pipeline_complet.py
│   ├── pipeline_steps.py              ← orchestrateur intermédiaire
│   ├── bootstrap.py                   ← chargement .env
│   ├── aggregate/aggregate.py         ← 631 lignes, nettoyage + enrichissement
│   ├── collect/
│   │   ├── collecter.py               ← orchestrateur collecte
│   │   ├── classification.py          ← moteur de classification (497 lignes)
│   │   └── sources/                   ← 5 connecteurs
│   ├── database/
│   │   ├── models.py                  ← ORM SQLAlchemy
│   │   ├── import_data.py             ← 211 lignes
│   │   └── migrations/001 + 002.sql
│   ├── api/main.py + auth.py + schemas.py
│   ├── queries/                       ← 4 fichiers SQL/HQL
│   ├── docker/hive/ + hue/
│   ├── docker-compose.yml             ← 4 services
│   ├── data/                          ← 298 MB de fichiers non versionnés
│   └── tests/                         ← 7 fichiers de tests
│
├── data_CNIL/                         ← CSV source hors package
└── pytest-cache-files-*/             ← 55 dossiers de cache orphelins
```

---

## 2. Problèmes critiques (bloquants ou risqués)

### 🔴 P1 — Le dossier `data/` fait 298 MB et accumule des doublons massifs

| Fichier | Taille | Statut |
|---|---|---|
| `clean_dataset.csv` | 17,9 MB | Doublon exact de `3_dataset_enrichi.csv` |
| `3_dataset_enrichi.csv` | 17,9 MB | Source canonique |
| `2_dataset_nettoye.csv` | 18,1 MB | Intermédiaire inutile en production |
| `6_dataset_ml.csv` | 20,2 MB | Dérivé recalculable |
| 22 fichiers `raw_*.json` | ~220 MB | Accumulation non nettoyée |
| `hive_phishstats_cache.json` | 4,1 MB | Cache Hive jamais purgé |

**Problème** : `clean_dataset.csv` est un lien physique vers `3_dataset_enrichi.csv` (géré dans `save_enriched_stage`), donc le contenu est identique en double. Les 22 fichiers `raw_*.json` s'accumulent à chaque exécution sans rotation ni suppression.

**Impact** : `data/` grossit indéfiniment. Pas de `.gitignore` propre pour ce dossier.

---

### 🔴 P2 — 55 dossiers `pytest-cache-files-*` orphelins à la racine workspace

pytest est configuré pour écrire son cache dans la **racine du workspace** (`c:\Projets RNCP\Projet 1 - Bloc 1 - C1 a 5\`) au lieu du dossier `arnaqueradar/`. Cause : absence de `pytest.ini` / `pyproject.toml` avec `testpaths` et `cache_dir` configurés. Ces 55 dossiers ne servent à rien et polluent la racine.

---

### 🔴 P3 — `data_CNIL/` à la racine workspace, hors package

Le dossier `data_CNIL/cnil_violations.csv` est positionné **en dehors** du package `arnaqueradar/`. Le connecteur `cnil_csv.py` résout son chemin via `PROJECT_ROOT`, ce qui suppose que le script est toujours exécuté depuis `arnaqueradar/`. Si ce n'est pas le cas, le fichier est introuvable silencieusement.

---

### 🔴 P4 — Double couche de connexion psycopg2 avec logique conflictuelle

Dans `pg_history.py` et `import_data.py`, la connexion psycopg2 a été refactorée plusieurs fois et contient encore des références résiduelles à `DATABASE_URL` commentées ou partielles. `models.py` utilise `sqlalchemy.engine.URL.create()` (correct), mais les deux autres fichiers utilisent des `kwargs` directs. Il n'existe pas de couche de connexion unifiée — chaque module gère sa propre connexion.

---

## 3. Redondances structurelles

### 🟠 R1 — Trois orchestrateurs pour la même chose

| Fichier | Rôle déclaré | Rôle réel |
|---|---|---|
| `collect/collecter.py` | Point d'entrée collecte | Appelle les 5 sources, sauvegarde JSON |
| `pipeline_steps.py` | Orchestrateur pédagogique | Wraps `collecter.py` + `aggregate.py` + `import_data.py` |
| `7_pipeline_complet.py` | "Pipeline complet" | 3 lignes qui appellent `pipeline_steps.stage_7_full_pipeline()` |

`7_pipeline_complet.py` est un wrapper d'un wrapper d'un wrapper. Il n'ajoute aucune valeur.

---

### 🟠 R2 — Scripts numérotés `1_collecter.py` à `6_preparer_dataset_ml.py` redondants

Ces 6 scripts contiennent chacun ~15-30 lignes qui appellent une seule fonction de `pipeline_steps.py`. Exemple de `1_collecter.py` :

```python
from pipeline_steps import stage_1_collect
result = stage_1_collect()
```

Ce sont des alias scripts sans logique propre. Ils doublonnent le `__main__` déjà présent dans `collect/collecter.py` et `aggregate/aggregate.py`.

---

### 🟠 R3 — `clean_dataset.csv` est un doublon physique de `3_dataset_enrichi.csv`

La fonction `save_enriched_stage` tente un `os.link()` (lien dur) puis retombe sur une copie. Résultat : **deux fichiers identiques de 18 MB** sur le disque, l'un étant l'alias historique de l'autre. Aucune valeur ajoutée.

---

### 🟠 R4 — `2_dataset_nettoye.csv` est un intermédiaire de débogage promu en artefact permanent

Ce fichier de 18 MB est produit à chaque exécution mais n'est utilisé que si `3_enrichir.py` est exécuté de manière isolée (sans passer le DataFrame en mémoire). En exécution pipeline normale, il est inutile.

---

### 🟠 R5 — `bootstrap.py` duplique une logique déjà présente dans chaque module

Chaque module (`collecter.py`, `aggregate.py`, `pipeline_steps.py`) fait :
```python
PROJECT_ROOT = Path(__file__).resolve().parents[N]
sys.path.insert(0, str(PROJECT_ROOT))
from bootstrap import load_project_env
load_project_env()
```

Si `bootstrap.py` est censé centraliser cette logique, pourquoi chaque module recalcule-t-il `PROJECT_ROOT` de son côté avant de l'importer ?

---

### 🟠 R6 — `docker-compose.yml` contient Hue (interface graphique) non utilisé par le pipeline

Le fichier Docker Compose déclare 4 services : `metastore`, `hive`, `hue-db`, `hue`. Hue est une interface web Hadoop. Elle n'est référencée nulle part dans le code Python et n'est pas nécessaire au fonctionnement du pipeline. C'est 2 services Docker supplémentaires (dont un PostgreSQL dédié `hue-db`) lancés pour rien.

---

## 4. Failles de conception

### 🟡 F1 — Pas de gestion de rétention sur `data/raw_*.json`

À chaque exécution de `1_collecter.py`, un nouveau fichier `raw_YYYYMMDD_HHMMSS.json` est créé. Il n'existe aucun mécanisme de nettoyage. Après quelques semaines d'usage intensif, `data/` peut atteindre plusieurs GB. Solution : conserver uniquement les N derniers fichiers bruts (ex: 3).

---

### 🟡 F2 — Le cache Hive `hive_phishstats_cache.json` (4,1 MB) n'a pas de TTL

Le connecteur Hive maintient un cache JSON local. Il n'existe pas de logique de TTL (time-to-live) : ce fichier n'est jamais invalidé automatiquement. Des données de phishing qui ont plusieurs semaines restent dans le cache indéfiniment.

---

### 🟡 F3 — `aggregate.py` fait 631 lignes — trop de responsabilités dans un seul module

Ce fichier mélange :
- Chargement des données brutes (I/O)
- Nettoyage technique
- Enrichissement métier
- Contrôle qualité et rapports
- Sauvegarde des artefacts intermédiaires

C'est une violation du principe de responsabilité unique (SRP). La logique de nettoyage est distincte de l'enrichissement mais tout est dans le même fichier.

---

### 🟡 F4 — `classification.py` n'est pas testé directement

Les tests unitaires couvrent les sources (`test_urlhaus.py`, `test_malwaretips.py`, etc.) et l'API (`test_api.py`), mais aucun test ne cible `classification.py` directement. Or c'est le moteur central de qualification — le module avec le plus fort impact sur la qualité du dataset final.

---

### 🟡 F5 — `import_data.py` fait 211 lignes mais résout les FK dans le script

La résolution des clés étrangères (`type_id`, `region_id`, `source_id`) se fait manuellement dans `import_data.py` avec des lookups dictionnaire. Avec SQLAlchemy déjà présent (`models.py`), cette logique aurait dû être portée par l'ORM, ce qui aurait évité les mappings manuels `TYPE_CODE_MAP` et `SOURCE_CODE_MAP`.

---

### 🟡 F6 — La migration `001_init.sql` et la migration `002_align_runtime_schema.sql` sont partiellement redondantes

`002` ajoute des colonnes (`canal`, `nature_technique`, `score_confiance`, etc.) qui auraient dû être dans `001` dès le départ. Le schéma initial ne reflétait pas le modèle de données réel du pipeline. Cela indique une conception initiale incomplète rattrapée a posteriori.

---

### 🟡 F7 — `models.py` déclare `SignalementHistorique` mais `signalement_sources` (table de migration 002) n'a pas de modèle ORM

La table `signalement_sources` créée dans `002_align_runtime_schema.sql` n'a aucun modèle SQLAlchemy correspondant dans `models.py`. Le code ne peut donc pas y accéder via l'ORM.

---

### 🟡 F8 — `_test_conn.py` traîne dans la racine du projet

Ce fichier de test de connexion ad hoc a été créé pendant le débogage et n'a jamais été supprimé. Il n'a pas vocation à rester en production.

---

## 5. Fichiers strictement inutiles / à supprimer

| Fichier / Dossier | Raison |
|---|---|
| `_test_conn.py` | Script de debug temporaire, jamais supprimé |
| `1_collecter.py` à `6_preparer_dataset_ml.py` | Wrappers d'une ligne sur `pipeline_steps.py` ; les `__main__` des modules suffisent |
| `7_pipeline_complet.py` | Wrapper de `pipeline_steps.stage_7_full_pipeline()`, redondant |
| `data/raw_20260513_*.json` (21 anciens fichiers) | Archivés automatiquement, jamais purgés — ~220 MB inutiles |
| `data/2_dataset_nettoye.csv` | Intermédiaire recalculable en mémoire |
| `data/clean_dataset.csv` | Doublon de `3_dataset_enrichi.csv` |
| `data/6_dataset_ml.csv` | Dérivé recalculable depuis `3_dataset_enrichi.csv` |
| `pytest-cache-files-*/` × 55 | Cache pytest orphelin à la racine workspace |
| `docker/hue/` | Interface Hue non utilisée par le pipeline |
| Service `hue` + `hue-db` dans `docker-compose.yml` | Non utilisés, 2 services Docker pour rien |
| `Idée de Mr` (racine workspace) | Fichier texte personnel, ne doit pas être dans un dépôt |

---

## 6. Améliorations structurelles recommandées

### ✅ A1 — Ajouter `pytest.ini` pour corriger le cache

```ini
[pytest]
testpaths = tests
cache_dir = .pytest_cache
```
Empêche les 55 dossiers orphelins de se recréer.

---

### ✅ A2 — Rotation automatique des fichiers `raw_*.json`

Dans `collecter.py/_save_raw_data()`, après la sauvegarde :
```python
# Conserver uniquement les 3 derniers fichiers bruts
raw_files = sorted(glob.glob(str(DATA_DIR / "raw_*.json")))
for old_file in raw_files[:-3]:
    Path(old_file).unlink()
```

---

### ✅ A3 — Supprimer `clean_dataset.csv` comme alias et utiliser un seul nom canonique

Renommer `3_dataset_enrichi.csv` → `clean_dataset.csv` directement. Supprimer le lien dur / la copie. Mettre à jour `import_data.py` pour lire `clean_dataset.csv`.

---

### ✅ A4 — Ajouter un TTL sur le cache Hive

```python
CACHE_MAX_AGE_HOURS = 24
cache_age = time.time() - cache_path.stat().st_mtime
if cache_age > CACHE_MAX_AGE_HOURS * 3600:
    cache_path.unlink()
```

---

### ✅ A5 — Scinder `aggregate.py` en 3 modules

```
aggregate/
├── __init__.py
├── cleaner.py          ← clean_raw_dataframe() uniquement
├── enricher.py         ← enrich_clean_dataframe() + classification
├── quality.py          ← build_quality_report() + build_other_review_sample()
└── pipeline.py         ← run_cleaning_stage(), run_enrichment_stage(), etc.
```

---

### ✅ A6 — Ajouter le modèle ORM `SignalementSource` pour `signalement_sources`

Compléter `models.py` avec le modèle correspondant à la table créée dans `002_align_runtime_schema.sql`.

---

### ✅ A7 — Supprimer Hue de `docker-compose.yml`

Retirer les services `hue` et `hue-db` du `docker-compose.yml`. Si une interface de requêtage Hive est nécessaire, DBeaver (client local) est suffisant et ne consomme pas de ressources Docker.

---

### ✅ A8 — Déplacer `data_CNIL/` à l'intérieur de `arnaqueradar/data/`

```
arnaqueradar/data/sources/cnil_violations.csv
```
Et mettre à jour le chemin dans `cnil_csv.py`.

---

## 7. Résumé chiffré

| Catégorie | Constat |
|---|---|
| **Espace disque libérable immédiatement** | ~255 MB (raw anciens + doublons CSV) |
| **Dossiers orphelins à supprimer** | 55 (`pytest-cache-files-*`) |
| **Fichiers Python redondants** | 7 (scripts 1 à 7 + `_test_conn.py`) |
| **Services Docker inutiles** | 2 (Hue + hue-db) |
| **Modèles ORM manquants** | 1 (`SignalementSource`) |
| **Tests manquants sur module critique** | 1 (`classification.py`) |
| **Module à scinder** | 1 (`aggregate.py`, 631 lignes) |

