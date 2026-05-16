-- ============================================================================
-- PostgreSQL local - verifications utiles dans pgAdmin4
-- Base cible : arnaqueradar
-- Usage :
--   1. ouvrir Query Tool dans pgAdmin4
--   2. executer les requetes souhaitees
-- ============================================================================

-- 1. Verification generale
SELECT current_database() AS base_courante;

SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;

-- 2. Volumetrie principale
SELECT 'signalements_historique' AS table_name, COUNT(*) AS nb_lignes FROM signalements_historique
UNION ALL
SELECT 'signalements', COUNT(*) FROM signalements
UNION ALL
SELECT 'signalement_sources', COUNT(*) FROM signalement_sources;

-- 3. Top sources dans le stockage final
SELECT s.code,
       s.type_source,
       COUNT(*) AS nb_signalements
FROM signalements sig
JOIN sources s ON s.id = sig.source_id
GROUP BY s.code, s.type_source
ORDER BY nb_signalements DESC, s.code;

-- 4. Top types d'arnaques
SELECT t.code AS type_arnaque,
       COUNT(*) AS nb_signalements
FROM signalements sig
JOIN types_arnaque t ON t.id = sig.type_id
GROUP BY t.code
ORDER BY nb_signalements DESC, t.code;

-- 5. Controle de la source 4
SELECT COUNT(*) AS historique_exploitable
FROM signalements_historique
WHERE verified = TRUE
  AND COALESCE(statut_traitement, 'nouveau') IN ('valide', 'confirme');

SELECT id,
       url,
       type_arnaque,
       region,
       date_signalement,
       canal,
       source_interne,
       nb_signalements
FROM signalements_historique
WHERE verified = TRUE
  AND COALESCE(statut_traitement, 'nouveau') IN ('valide', 'confirme')
ORDER BY date_signalement DESC, id DESC
LIMIT 20;

-- 6. Controle du stockage consolide
SELECT sig.id,
       sig.url,
       t.code AS type_arnaque,
       r.nom AS region,
       s.code AS source_primaire,
       sig.date_signalement,
       sig.nb_signalements,
       sig.score_confiance
FROM signalements sig
JOIN types_arnaque t ON t.id = sig.type_id
LEFT JOIN regions r ON r.id = sig.region_id
JOIN sources s ON s.id = sig.source_id
ORDER BY sig.date_signalement DESC, sig.id DESC
LIMIT 20;
