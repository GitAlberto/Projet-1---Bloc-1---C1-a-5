-- =============================================================================
-- Migration 002 - Alignement du schema consolide / evidences
-- Projet : ArnaqueRadar
--
-- Objectif :
-- - mettre a niveau les bases deja creees avant le modele enrichi
-- - ajouter les colonnes exposees par le pipeline moderne
-- - introduire la table de corroboration `signalement_sources`
-- - garder le schema SQL comme seule source de verite
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Table principale consolidee
-- ---------------------------------------------------------------------------
ALTER TABLE signalements
    ADD COLUMN IF NOT EXISTS nb_signalements       INTEGER      NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS canal                 VARCHAR(30),
    ADD COLUMN IF NOT EXISTS nature_technique      VARCHAR(50),
    ADD COLUMN IF NOT EXISTS score_confiance       NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS type_raw              VARCHAR(100),
    ADD COLUMN IF NOT EXISTS source_category_raw   VARCHAR(255),
    ADD COLUMN IF NOT EXISTS keywords_matched      TEXT,
    ADD COLUMN IF NOT EXISTS classifier_version    VARCHAR(50);

CREATE UNIQUE INDEX IF NOT EXISTS uq_signalement_url_date
    ON signalements (url, date_signalement);

CREATE INDEX IF NOT EXISTS idx_signalement_type ON signalements (type_id);
CREATE INDEX IF NOT EXISTS idx_signalement_region ON signalements (region_id);
CREATE INDEX IF NOT EXISTS idx_signalement_source ON signalements (source_id);
CREATE INDEX IF NOT EXISTS idx_signalement_date ON signalements (date_signalement DESC);

-- ---------------------------------------------------------------------------
-- Table de preuves / corroborations par source
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signalement_sources (
    id                    SERIAL PRIMARY KEY,
    signalement_id        INTEGER NOT NULL REFERENCES signalements(id) ON DELETE CASCADE,
    source_id             INTEGER NOT NULL REFERENCES sources(id),
    date_observation      DATE NOT NULL,
    verified              BOOLEAN DEFAULT FALSE,
    titre                 VARCHAR(500),
    region_raw            VARCHAR(100),
    canal                 VARCHAR(30),
    nature_technique      VARCHAR(50),
    score_confiance       NUMERIC(4,3),
    type_raw              VARCHAR(100) NOT NULL DEFAULT '',
    source_category_raw   VARCHAR(255),
    keywords_matched      TEXT,
    classifier_version    VARCHAR(50),
    source_interne        VARCHAR(100) NOT NULL DEFAULT '',
    nb_signalements       INTEGER NOT NULL DEFAULT 1,
    created_at            TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_signalement_source_observation UNIQUE (
        signalement_id, source_id, date_observation, source_interne, type_raw
    )
);

CREATE INDEX IF NOT EXISTS idx_signalement_sources_signalement
    ON signalement_sources (signalement_id);
CREATE INDEX IF NOT EXISTS idx_signalement_sources_source
    ON signalement_sources (source_id);
CREATE INDEX IF NOT EXISTS idx_signalement_sources_date
    ON signalement_sources (date_observation DESC);

-- ---------------------------------------------------------------------------
-- Historique PostgreSQL utilise comme source 4
-- ---------------------------------------------------------------------------
ALTER TABLE signalements_historique
    ADD COLUMN IF NOT EXISTS canal                  VARCHAR(30)   NOT NULL DEFAULT 'web',
    ADD COLUMN IF NOT EXISTS statut_traitement      VARCHAR(30)   NOT NULL DEFAULT 'nouveau',
    ADD COLUMN IF NOT EXISTS description_signalement TEXT,
    ADD COLUMN IF NOT EXISTS analyste               VARCHAR(100),
    ADD COLUMN IF NOT EXISTS source_interne         VARCHAR(100)  NOT NULL DEFAULT 'portail_web',
    ADD COLUMN IF NOT EXISTS nb_signalements        INTEGER       NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_hist_date ON signalements_historique (date_signalement);
CREATE INDEX IF NOT EXISTS idx_hist_status ON signalements_historique (statut_traitement);
CREATE INDEX IF NOT EXISTS idx_hist_verified ON signalements_historique (verified);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hist_url_date_source_interne
    ON signalements_historique (url, date_signalement, source_interne);

-- ---------------------------------------------------------------------------
-- Typologie et sources actives
-- ---------------------------------------------------------------------------
INSERT INTO types_arnaque (code, libelle, description) VALUES
    ('malware_distribution', 'Distribution de malware', 'URL ou infrastructure servant a distribuer une charge malveillante')
ON CONFLICT (code) DO NOTHING;

INSERT INTO sources (code, libelle, url, type_source) VALUES
    ('urlhaus', 'URLhaus', 'https://urlhaus-api.abuse.ch/', 'api'),
    ('malwaretips', 'MalwareTips', 'https://malwaretips.com/blogs/category/adware/', 'scraping'),
    ('cnil_csv', 'CNIL CSV', 'https://www.data.gouv.fr/datasets/notifications-a-la-cnil-de-violations-de-donnees-a-caractere-personnel', 'csv'),
    ('pg_history', 'Historique PostgreSQL', 'postgresql://localhost/arnaqueradar', 'sql'),
    ('hive_logs', 'Hive / PhishStats', 'hive://localhost:10000/default', 'bigdata')
ON CONFLICT (code) DO UPDATE
SET
    libelle = EXCLUDED.libelle,
    url = EXCLUDED.url,
    type_source = EXCLUDED.type_source;

-- Les anciennes sources peuvent rester presentes dans une base deja alimentee.
-- On ne les supprime pas ici pour eviter toute rupture de cle etrangere sur
-- des signalements historiques deja importes.

COMMIT;
