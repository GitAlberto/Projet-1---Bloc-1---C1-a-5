-- =============================================================================
-- Migration 001 : Initialisation du schema ArnaqueRadar
-- =============================================================================

-- -------------------------
-- Table de reference : types d'arnaques
-- -------------------------
CREATE TABLE IF NOT EXISTS types_arnaque (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50)  NOT NULL UNIQUE,
    libelle     VARCHAR(100) NOT NULL,
    description TEXT
);

-- -------------------------
-- Table de reference : regions francaises
-- -------------------------
CREATE TABLE IF NOT EXISTS regions (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(10)  NOT NULL UNIQUE,
    nom         VARCHAR(100) NOT NULL
);

-- -------------------------
-- Table de reference : sources de donnees
-- -------------------------
CREATE TABLE IF NOT EXISTS sources (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50)  NOT NULL UNIQUE,
    libelle     VARCHAR(100) NOT NULL,
    url         VARCHAR(255),
    type_source VARCHAR(20)  NOT NULL CHECK (type_source IN ('api', 'scraping', 'csv', 'sql', 'bigdata'))
);

-- -------------------------
-- Table principale : signalements consolides
-- -------------------------
CREATE TABLE IF NOT EXISTS signalements (
    id                  SERIAL PRIMARY KEY,
    url                 VARCHAR(2048) NOT NULL,
    type_id             INTEGER NOT NULL REFERENCES types_arnaque(id),
    region_id           INTEGER REFERENCES regions(id),
    source_id           INTEGER NOT NULL REFERENCES sources(id),
    date_signalement    DATE NOT NULL,
    verified            BOOLEAN DEFAULT FALSE,
    titre               VARCHAR(500),
    nb_signalements     INTEGER DEFAULT 1,
    canal               VARCHAR(30),
    nature_technique    VARCHAR(50),
    score_confiance     NUMERIC(4,3),
    type_raw            VARCHAR(100),
    source_category_raw VARCHAR(255),
    keywords_matched    TEXT,
    classifier_version  VARCHAR(50),
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_signalement_url_date UNIQUE (url, date_signalement)
);

-- -------------------------
-- Table de preuves / corroborations source par source
-- -------------------------
CREATE TABLE IF NOT EXISTS signalement_sources (
    id                  SERIAL PRIMARY KEY,
    signalement_id      INTEGER NOT NULL REFERENCES signalements(id) ON DELETE CASCADE,
    source_id           INTEGER NOT NULL REFERENCES sources(id),
    date_observation    DATE NOT NULL,
    verified            BOOLEAN DEFAULT FALSE,
    titre               VARCHAR(500),
    region_raw          VARCHAR(100),
    canal               VARCHAR(30),
    nature_technique    VARCHAR(50),
    score_confiance     NUMERIC(4,3),
    type_raw            VARCHAR(100) NOT NULL DEFAULT '',
    source_category_raw VARCHAR(255),
    keywords_matched    TEXT,
    classifier_version  VARCHAR(50),
    source_interne      VARCHAR(100) NOT NULL DEFAULT '',
    nb_signalements     INTEGER NOT NULL DEFAULT 1,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_signalement_source_observation
        UNIQUE (signalement_id, source_id, date_observation, source_interne, type_raw)
);

-- -------------------------
-- Table historique : source PostgreSQL
-- -------------------------
CREATE TABLE IF NOT EXISTS signalements_historique (
    id                      SERIAL PRIMARY KEY,
    url                     VARCHAR(2048) NOT NULL,
    type_arnaque            VARCHAR(50)   NOT NULL,
    region                  VARCHAR(100),
    date_signalement        DATE          NOT NULL,
    source                  VARCHAR(50)   NOT NULL DEFAULT 'pg_history',
    verified                BOOLEAN       DEFAULT FALSE,
    canal                   VARCHAR(30)   NOT NULL DEFAULT 'web',
    statut_traitement       VARCHAR(30)   NOT NULL DEFAULT 'nouveau',
    description_signalement TEXT,
    analyste                VARCHAR(100),
    source_interne          VARCHAR(100)  NOT NULL DEFAULT 'portail_web',
    nb_signalements         INTEGER       NOT NULL DEFAULT 1,
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- -------------------------
-- Index de performance
-- -------------------------
CREATE INDEX IF NOT EXISTS idx_signalements_date         ON signalements (date_signalement);
CREATE INDEX IF NOT EXISTS idx_signalements_type_id      ON signalements (type_id);
CREATE INDEX IF NOT EXISTS idx_signalements_source_id    ON signalements (source_id);
CREATE INDEX IF NOT EXISTS idx_signalements_url          ON signalements USING hash (url);
CREATE INDEX IF NOT EXISTS idx_signalement_sources_sig   ON signalement_sources (signalement_id);
CREATE INDEX IF NOT EXISTS idx_signalement_sources_src   ON signalement_sources (source_id);
CREATE INDEX IF NOT EXISTS idx_signalement_sources_date  ON signalement_sources (date_observation);
CREATE INDEX IF NOT EXISTS idx_hist_date                 ON signalements_historique (date_signalement);
CREATE INDEX IF NOT EXISTS idx_hist_status               ON signalements_historique (statut_traitement);
CREATE INDEX IF NOT EXISTS idx_hist_verified             ON signalements_historique (verified);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hist_url_date_source_interne
    ON signalements_historique (url, date_signalement, source_interne);

-- -------------------------
-- Donnees de reference : types d'arnaques
-- -------------------------
INSERT INTO types_arnaque (code, libelle, description) VALUES
    ('phishing',             'Hameconnage',             'Tentative de vol de donnees via un faux site ou email'),
    ('malware_distribution', 'Distribution de malware', 'URL malveillante diffusant un executable, chargeur ou payload technique'),
    ('sms_frauduleux',       'SMS frauduleux',          'Smishing : arnaque par SMS (faux transporteur, impots, etc.)'),
    ('violation_rgpd',       'Violation RGPD',          'Fuite ou traitement illicite de donnees personnelles'),
    ('arnaque_achat',        'Arnaque a l''achat',      'Faux vendeur, produit non livre sur plateforme de vente'),
    ('fraude_cpf',           'Fraude CPF',              'Usurpation du compte formation professionnel'),
    ('faux_support',         'Faux support technique',  'Escroquerie au faux conseiller bancaire ou informatique'),
    ('autre',                'Autre',                   'Arnaque ne correspondant pas aux categories ci-dessus')
ON CONFLICT (code) DO NOTHING;

-- -------------------------
-- Donnees de reference : regions francaises
-- -------------------------
INSERT INTO regions (code, nom) VALUES
    ('ARA', 'Auvergne-Rhone-Alpes'),
    ('BFC', 'Bourgogne-Franche-Comte'),
    ('BRE', 'Bretagne'),
    ('CVL', 'Centre-Val de Loire'),
    ('COR', 'Corse'),
    ('GES', 'Grand Est'),
    ('HDF', 'Hauts-de-France'),
    ('IDF', 'Ile-de-France'),
    ('NOR', 'Normandie'),
    ('NAQ', 'Nouvelle-Aquitaine'),
    ('OCC', 'Occitanie'),
    ('PDL', 'Pays de la Loire'),
    ('PAC', 'Provence-Alpes-Cote d''Azur'),
    ('GUA', 'Guadeloupe'),
    ('MTQ', 'Martinique'),
    ('GUY', 'Guyane'),
    ('REU', 'La Reunion'),
    ('MAY', 'Mayotte'),
    ('INC', 'Inconnue')
ON CONFLICT (code) DO NOTHING;

-- -------------------------
-- Donnees de reference : sources
-- -------------------------
INSERT INTO sources (code, libelle, url, type_source) VALUES
    ('urlhaus',     'URLhaus',                  'https://urlhaus-api.abuse.ch/v1/urls/recent/', 'api'),
    ('malwaretips', 'MalwareTips Scam Reports', 'https://malwaretips.com/blogs/category/scam-reports/', 'scraping'),
    ('cnil_csv',    'CNIL Open Data',           'https://www.data.gouv.fr/', 'csv'),
    ('pg_history',  'Historique PostgreSQL',    NULL, 'sql'),
    ('hive_logs',   'Logs Big Data Hive',       NULL, 'bigdata')
ON CONFLICT (code) DO NOTHING;
