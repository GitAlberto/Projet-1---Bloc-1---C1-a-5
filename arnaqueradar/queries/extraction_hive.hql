-- =============================================================================
-- Requetes HiveQL d'extraction - ArnaqueRadar
-- Environnement : Apache Hive 3.1.3 / HiveServer2
-- Table source  : logs_arnaques (table simple non partitionnee)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Requete 1 : volumetrie mensuelle par type
--
-- La table live `logs_arnaques` n'est pas partitionnee par annee / mois.
-- L'optimisation se fait donc ici par filtrage sur `event_date` et par
-- reduction du volume via `SUM(COALESCE(nb_signalements, 1))`.
-- -----------------------------------------------------------------------------
SELECT
    YEAR(event_date)                              AS annee,
    MONTH(event_date)                             AS mois,
    type_arnaque,
    SUM(COALESCE(nb_signalements, 1))             AS nb_signalements,
    COUNT(DISTINCT url_pattern)                   AS nb_url_uniques
FROM logs_arnaques
WHERE event_date >= ADD_MONTHS(CURRENT_DATE, -12)
GROUP BY
    YEAR(event_date),
    MONTH(event_date),
    type_arnaque
ORDER BY annee ASC, mois ASC, nb_signalements DESC;


-- -----------------------------------------------------------------------------
-- Requete 2 : top campagnes observees recemment
--
-- Objectif : identifier les couples URL / type les plus actifs sur les
-- 30 derniers jours pour un reporting de veille.
-- -----------------------------------------------------------------------------
SELECT
    url_pattern                    AS url,
    type_arnaque,
    region,
    SUM(COALESCE(nb_signalements, 1)) AS nb_signalements,
    MIN(event_date)               AS premiere_observation,
    MAX(event_date)               AS derniere_observation
FROM logs_arnaques
WHERE event_date >= DATE_SUB(CURRENT_DATE, 30)
GROUP BY url_pattern, type_arnaque, region
ORDER BY nb_signalements DESC
LIMIT 100;
