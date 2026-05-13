-- =============================================================================
-- Migration 001 : Initialisation du modèle physique de données ArnaqueRadar
-- Basé sur le MCD Merise :
--   SIGNALEMENT appartient-à TYPE_ARNAQUE (n..1)
--   SIGNALEMENT localisé-dans REGION (n..1)
--   SIGNALEMENT provient-de SOURCE (n..1)
-- =============================================================================

-- -------------------------
-- Table de référence : types d'arnaques
-- -------------------------
CREATE TABLE IF NOT EXISTS types_arnaque (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50)  NOT NULL UNIQUE,
    libelle     VARCHAR(100) NOT NULL,
    description TEXT
);

-- -------------------------
-- Table de référence : régions françaises (métropole + DROM)
-- -------------------------
CREATE TABLE IF NOT EXISTS regions (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(10)  NOT NULL UNIQUE,
    nom         VARCHAR(100) NOT NULL
);

-- -------------------------
-- Table de référence : sources de données
-- -------------------------
CREATE TABLE IF NOT EXISTS sources (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(50)  NOT NULL UNIQUE,
    libelle     VARCHAR(100) NOT NULL,
    url         VARCHAR(255),
    type_source VARCHAR(20)  NOT NULL CHECK (type_source IN ('api', 'scraping', 'csv', 'sql', 'bigdata'))
);

-- -------------------------
-- Table principale : signalements d'arnaques
-- -------------------------
CREATE TABLE IF NOT EXISTS signalements (
    id                SERIAL PRIMARY KEY,
    url               VARCHAR(2048) NOT NULL,
    type_id           INTEGER NOT NULL REFERENCES types_arnaque(id),
    region_id         INTEGER REFERENCES regions(id),
    source_id         INTEGER NOT NULL REFERENCES sources(id),
    date_signalement  DATE NOT NULL,
    verified          BOOLEAN DEFAULT FALSE,
    titre             VARCHAR(500),
    nb_signalements   INTEGER DEFAULT 1,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_signalement_url_date UNIQUE (url, date_signalement)
);

-- -------------------------
-- Table historique (identique à signalements, utilisée par la source pg_history)
-- -------------------------
CREATE TABLE IF NOT EXISTS signalements_historique (
    id                SERIAL PRIMARY KEY,
    url               VARCHAR(2048) NOT NULL,
    type_arnaque      VARCHAR(50)   NOT NULL,
    region            VARCHAR(100),
    date_signalement  DATE NOT NULL,
    source            VARCHAR(50)   NOT NULL DEFAULT 'pg_history',
    verified          BOOLEAN DEFAULT FALSE,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- -------------------------
-- Index pour améliorer les performances de recherche
-- -------------------------
CREATE INDEX IF NOT EXISTS idx_signalements_date    ON signalements (date_signalement);
CREATE INDEX IF NOT EXISTS idx_signalements_type_id ON signalements (type_id);
CREATE INDEX IF NOT EXISTS idx_signalements_url     ON signalements USING hash (url);
CREATE INDEX IF NOT EXISTS idx_hist_date            ON signalements_historique (date_signalement);

-- -------------------------
-- Données de référence : types d'arnaques
-- -------------------------
INSERT INTO types_arnaque (code, libelle, description) VALUES
    ('phishing',       'Hameçonnage',           'Tentative de vol de données via un faux site ou email'),
    ('sms_frauduleux', 'SMS frauduleux',         'Smishing : arnaque par SMS (faux Chronopost, impôts, etc.)'),
    ('violation_rgpd', 'Violation RGPD',         'Fuite ou traitement illicite de données personnelles'),
    ('arnaque_achat',  'Arnaque à l''achat',     'Faux vendeur, produit non livré sur plateforme de vente'),
    ('fraude_cpf',     'Fraude CPF',             'Usurpation du compte formation professionnel'),
    ('faux_support',   'Faux support technique', 'Escroquerie au faux conseiller bancaire ou informatique'),
    ('autre',          'Autre',                  'Arnaque ne correspondant pas aux catégories ci-dessus')
ON CONFLICT (code) DO NOTHING;

-- -------------------------
-- Données de référence : régions françaises
-- -------------------------
INSERT INTO regions (code, nom) VALUES
    ('ARA',  'Auvergne-Rhône-Alpes'),
    ('BFC',  'Bourgogne-Franche-Comté'),
    ('BRE',  'Bretagne'),
    ('CVL',  'Centre-Val de Loire'),
    ('COR',  'Corse'),
    ('GES',  'Grand Est'),
    ('HDF',  'Hauts-de-France'),
    ('IDF',  'Île-de-France'),
    ('NOR',  'Normandie'),
    ('NAQ',  'Nouvelle-Aquitaine'),
    ('OCC',  'Occitanie'),
    ('PDL',  'Pays de la Loire'),
    ('PAC',  'Provence-Alpes-Côte d''Azur'),
    ('GUA',  'Guadeloupe'),
    ('MTQ',  'Martinique'),
    ('GUY',  'Guyane'),
    ('REU',  'La Réunion'),
    ('MAY',  'Mayotte'),
    ('INC',  'Inconnue')
ON CONFLICT (code) DO NOTHING;

-- -------------------------
-- Données de référence : sources de données
-- -------------------------
INSERT INTO sources (code, libelle, url, type_source) VALUES
    ('urlhaus',            'URLhaus API',            'https://urlhaus-api.abuse.ch/v1/urls/recent/',                    'api'),
    ('google_web_risk',    'Google Web Risk (legacy)', 'https://webrisk.googleapis.com/v1/uris:search',                 'api'),
    ('openphish',          'OpenPhish (legacy)',     'https://raw.githubusercontent.com/openphish/public_feed/refs/heads/main/feed.txt', 'api'),
    ('phishtank',          'PhishTank (legacy)',     'http://data.phishtank.com/data/online-valid.json', 'api'),
    ('cybermalveillance',  'Cybermalveillance.gouv', 'https://www.cybermalveillance.gouv.fr',            'scraping'),
    ('cnil_csv',           'CNIL Open Data',         'https://data.gouv.fr',                             'csv'),
    ('pg_history',         'Historique PostgreSQL',  NULL,                                               'sql'),
    ('hive_logs',          'Logs Big Data Hive',     NULL,                                               'bigdata')
ON CONFLICT (code) DO NOTHING;
