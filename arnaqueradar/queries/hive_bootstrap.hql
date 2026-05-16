-- =============================================================================
-- Bootstrap Hive - table logs_arnaques
-- Projet : ArnaqueRadar
--
-- Cette definition sert de reference pour :
-- - le stockage analytique live dans Hive
-- - les verifications manuelles dans Hue / Beeline / pyhive
-- - le bootstrap explicite PhishStats -> Hive
-- =============================================================================

CREATE TABLE IF NOT EXISTS logs_arnaques (
    url_pattern STRING,
    type_arnaque STRING,
    region STRING,
    event_date DATE,
    nb_signalements INT,
    title STRING,
    brand STRING,
    family STRING,
    tags STRING,
    host STRING,
    domain STRING
);
