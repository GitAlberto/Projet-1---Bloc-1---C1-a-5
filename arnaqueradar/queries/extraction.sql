-- =============================================================================
-- Requêtes SQL d'extraction — ArnaqueRadar
-- Base de données : PostgreSQL 15
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Requête 1 : Arnaques par région et type sur les 30 derniers jours
--
-- Objectif : donner une vision géographique et typologique de la menace
-- récente afin d'orienter les actions de sensibilisation.
--
-- Choix techniques :
--   - JOIN entre signalements, types_arnaque et regions pour dénormaliser
--     les libellés (évite de filtrer sur des IDs opaques côté client).
--   - WHERE date_signalement >= CURRENT_DATE - 30 : filtre sur 30 jours
--     glissants, indépendant du fuseau horaire.
--   - GROUP BY / ORDER BY : classement décroissant pour mettre en évidence
--     les combinaisons région/type les plus critiques.
--   - Optimisation : l'index idx_signalements_date accélère le filtre sur date.
-- -----------------------------------------------------------------------------
SELECT
    r.nom                   AS region,
    ta.libelle              AS type_arnaque,
    COUNT(s.id)             AS nb_signalements
FROM signalements s
JOIN types_arnaque ta ON s.type_id  = ta.id
JOIN regions       r  ON s.region_id = r.id
WHERE s.date_signalement >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY r.nom, ta.libelle
ORDER BY nb_signalements DESC;


-- -----------------------------------------------------------------------------
-- Requête 2 : Top 10 des domaines phishing les plus actifs
--
-- Objectif : identifier les noms de domaine les plus utilisés dans les
-- campagnes de phishing pour les transmettre aux équipes de blocage.
--
-- Choix techniques :
--   - SUBSTRING avec regex pour extraire le domaine depuis l'URL complète.
--     Pattern : tout ce qui suit "://" jusqu'au prochain "/" ou fin de chaîne.
--   - Jointure sur types_arnaque avec filtre code = 'phishing' pour
--     restreindre l'analyse aux seules arnaques par hameçonnage.
--   - LIMIT 10 : on ne remonte que les 10 domaines les plus signalés,
--     ce qui représente généralement 80% du volume selon la loi de Pareto.
--   - Optimisation : l'index idx_signalements_type_id couvre le filtre
--     sur type_id, réduisant le scan de table.
-- -----------------------------------------------------------------------------
SELECT
    SUBSTRING(s.url FROM '(?:https?://)?([^/]+)') AS domaine,
    COUNT(s.id)                                     AS nb_signalements
FROM signalements s
JOIN types_arnaque ta ON s.type_id = ta.id
WHERE ta.code = 'phishing'
GROUP BY domaine
ORDER BY nb_signalements DESC
LIMIT 10;


-- -----------------------------------------------------------------------------
-- Requête 3 : Évolution hebdomadaire du nombre de signalements sur 12 semaines
--
-- Objectif : suivre la tendance du volume de signalements semaine par semaine
-- pour détecter des pics d'activité (lancement de campagnes massives) ou
-- des creux (saisonnalité, effets des opérations de neutralisation).
--
-- Choix techniques :
--   - DATE_TRUNC('week', date_signalement) : regroupe chaque date dans la
--     semaine calendaire ISO correspondante (lundi = début de semaine).
--   - Filtre sur 84 jours (12 * 7) : garantit exactement 12 semaines
--     glissantes depuis aujourd'hui.
--   - ORDER BY semaine ASC : ordre chronologique pour faciliter le tracé
--     de courbes côté front-end / BI.
--   - Optimisation : l'index sur date_signalement permet au moteur de
--     réaliser un index scan au lieu d'un full table scan.
-- -----------------------------------------------------------------------------
SELECT
    DATE_TRUNC('week', s.date_signalement)::DATE AS semaine,
    COUNT(s.id)                                  AS nb_signalements
FROM signalements s
WHERE s.date_signalement >= CURRENT_DATE - INTERVAL '84 days'
GROUP BY semaine
ORDER BY semaine ASC;
