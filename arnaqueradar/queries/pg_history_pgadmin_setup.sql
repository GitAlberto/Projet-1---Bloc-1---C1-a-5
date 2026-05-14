-- ============================================================================
-- Source 4 PostgreSQL - preparation manuelle dans pgAdmin4
-- Base cible : arnaqueradar
-- Usage : ouvrir le Query Tool de pgAdmin4 sur la base arnaqueradar, puis
--         executer ce script une fois.
--
-- Volume cible :
--   Le generate_series ci-dessous est volontairement monte a 5000 lignes
--   afin de rendre la source PostgreSQL plus representative dans le volume
--   global du pipeline. Vous pouvez encore l'augmenter si besoin.
-- ============================================================================

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

ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS canal VARCHAR(30) NOT NULL DEFAULT 'web';
ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS statut_traitement VARCHAR(30) NOT NULL DEFAULT 'nouveau';
ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS description_signalement TEXT;
ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS analyste VARCHAR(100);
ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS source_interne VARCHAR(100) NOT NULL DEFAULT 'portail_web';
ALTER TABLE signalements_historique ADD COLUMN IF NOT EXISTS nb_signalements INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_hist_date ON signalements_historique (date_signalement);
CREATE INDEX IF NOT EXISTS idx_hist_status ON signalements_historique (statut_traitement);
CREATE INDEX IF NOT EXISTS idx_hist_verified ON signalements_historique (verified);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hist_url_date_source_interne
    ON signalements_historique (url, date_signalement, source_interne);

INSERT INTO signalements_historique (
    url,
    type_arnaque,
    region,
    date_signalement,
    source,
    verified,
    canal,
    statut_traitement,
    description_signalement,
    analyste,
    source_interne,
    nb_signalements
)
SELECT
    CASE type_arnaque
        WHEN 'phishing' THEN format('https://alerte-client-%s-securite.fr/connexion', gs)
        WHEN 'sms_frauduleux' THEN format('https://suivi-colis-%s-verification.fr/etat', gs)
        WHEN 'fraude_cpf' THEN format('https://compte-formation-%s-demarche.fr/dossier', gs)
        WHEN 'faux_support' THEN format('https://assistance-technique-%s-securite.fr/session', gs)
        ELSE format('https://boutique-flash-%s-paiement.fr/commande', gs)
    END AS url,
    type_arnaque,
    region,
    CURRENT_DATE - ((gs * 3) % 180) AS date_signalement,
    'pg_history' AS source,
    TRUE AS verified,
    canal,
    CASE WHEN gs % 5 = 0 THEN 'confirme' ELSE 'valide' END AS statut_traitement,
    CASE type_arnaque
        WHEN 'phishing' THEN format('Signalement interne : faux portail de connexion detecte par l''equipe fraude #%s', gs)
        WHEN 'sms_frauduleux' THEN format('Signalement interne : campagne SMS usurpant un transporteur detectee #%s', gs)
        WHEN 'fraude_cpf' THEN format('Signalement interne : demarchage abusif CPF remonte par le support #%s', gs)
        WHEN 'faux_support' THEN format('Signalement interne : faux support technique signale par un client #%s', gs)
        ELSE format('Signalement interne : faux site marchand remonte par le centre d''assistance #%s', gs)
    END AS description_signalement,
    analyste,
    source_interne,
    2 + (gs % 24) AS nb_signalements
FROM (
    SELECT
        gs,
        (ARRAY['phishing', 'sms_frauduleux', 'fraude_cpf', 'faux_support', 'arnaque_achat'])[1 + ((gs - 1) % 5)] AS type_arnaque,
        (ARRAY[
            'Ile-de-France',
            'Auvergne-Rhone-Alpes',
            'Bretagne',
            'Grand Est',
            'Hauts-de-France',
            'Normandie',
            'Nouvelle-Aquitaine',
            'Occitanie',
            'Pays de la Loire',
            'Provence-Alpes-Cote d''Azur'
        ])[1 + ((gs - 1) % 10)] AS region,
        (ARRAY['web', 'sms', 'email', 'appel'])[1 + ((gs - 1) % 4)] AS canal,
        (ARRAY['portail_web', 'centre_appels', 'partenaire_banque', 'backoffice_fraude'])[1 + ((gs - 1) % 4)] AS source_interne,
        (ARRAY['A. Martin', 'L. Bernard', 'S. Diallo', 'C. Dupont', 'N. Roy'])[1 + ((gs - 1) % 5)] AS analyste
    FROM generate_series(1, 5000) AS gs
) AS seed
ON CONFLICT (url, date_signalement, source_interne)
DO UPDATE SET
    type_arnaque = EXCLUDED.type_arnaque,
    region = EXCLUDED.region,
    verified = EXCLUDED.verified,
    canal = EXCLUDED.canal,
    statut_traitement = EXCLUDED.statut_traitement,
    description_signalement = EXCLUDED.description_signalement,
    analyste = EXCLUDED.analyste,
    nb_signalements = EXCLUDED.nb_signalements;

-- Verification rapide dans pgAdmin4 :
-- SELECT COUNT(*) FROM signalements_historique
-- WHERE verified = TRUE AND statut_traitement IN ('valide', 'confirme');
