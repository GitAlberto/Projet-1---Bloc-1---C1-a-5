-- =============================================================================
-- Requêtes HiveQL d'extraction — ArnaqueRadar
-- Environnement : Apache Hive 3.1.3 / HiveServer2
-- Table source  : logs_arnaques (partitionnée par annee, mois)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Requête 1 : Agrégation mensuelle du nombre de signalements par type
--
-- Objectif : produire un tableau de bord mensuel du volume d'arnaques
-- par catégorie, utile pour les rapports périodiques et les comparaisons
-- inter-mensuelles.
--
-- Optimisation par partitionnement :
--   La table logs_arnaques est partitionnée par (annee INT, mois INT).
--   En filtrant sur YEAR(event_date) = YEAR(CURRENT_DATE), Hive élimine
--   automatiquement les partitions des années précédentes (partition pruning).
--   Sans partitionnement, Hive devrait scanner l'intégralité du stockage HDFS,
--   ce qui représente potentiellement des téraoctets. Avec PARTITION BY,
--   seules les partitions de l'année courante sont lues, réduisant les I/O
--   de 70 à 95 % en production.
--
--   DISTRIBUTE BY type_arnaque permet à Hive de regrouper les lignes de même
--   type sur le même reducer, évitant les shuffles excessifs.
-- -----------------------------------------------------------------------------
SELECT
    YEAR(event_date)                  AS annee,
    MONTH(event_date)                 AS mois,
    type_arnaque,
    COUNT(*)                          AS nb_signalements,
    COUNT(DISTINCT url_pattern)       AS nb_domaines_uniques
FROM logs_arnaques
WHERE YEAR(event_date) = YEAR(CURRENT_DATE)
GROUP BY
    YEAR(event_date),
    MONTH(event_date),
    type_arnaque
DISTRIBUTE BY type_arnaque
ORDER BY annee ASC, mois ASC, nb_signalements DESC;


-- -----------------------------------------------------------------------------
-- Requête 2 : Détection des nouvelles campagnes d'arnaques (cette semaine)
--
-- Objectif : identifier les URLs qui apparaissent pour la PREMIÈRE FOIS
-- cette semaine dans les logs, ce qui signale le lancement d'une nouvelle
-- campagne de phishing ou de fraude. Ces URLs sont prioritaires pour le
-- blocage et la veille.
--
-- Stratégie :
--   On utilise une sous-requête pour trouver toutes les URLs dont la première
--   apparition (MIN(event_date)) tombe dans la semaine courante.
--   WEEKOFYEAR() permet de rester dans l'année courante sans risque de
--   confusion sur les semaines à cheval entre deux années.
--
-- Optimisation Hive :
--   - L'alias de sous-requête avec GROUP BY réduit le volume de données
--     antes le JOIN en agrégeant d'abord (stratégie "pré-agrégation").
--   - Le filtre HAVING sur WEEKOFYEAR limite les lignes transmises au
--     reducer principal.
--   - Si la table est bucketed par url_pattern, le JOIN peut bénéficier
--     d'un Map Join ou Bucket Map Join, évitant le shuffle réseau.
-- -----------------------------------------------------------------------------
SELECT
    url_pattern                         AS url,
    type_arnaque,
    region,
    nb_signalements,
    premiere_apparition
FROM (
    SELECT
        url_pattern,
        type_arnaque,
        region,
        COUNT(*)            AS nb_signalements,
        MIN(event_date)     AS premiere_apparition
    FROM logs_arnaques
    WHERE YEAR(event_date) = YEAR(CURRENT_DATE)
    GROUP BY url_pattern, type_arnaque, region
    HAVING WEEKOFYEAR(MIN(event_date)) = WEEKOFYEAR(CURRENT_DATE)
       AND YEAR(MIN(event_date))       = YEAR(CURRENT_DATE)
) nouvelles_campagnes
ORDER BY nb_signalements DESC
LIMIT 100;
