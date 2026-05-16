# Registre des traitements RGPD — ArnaqueRadar

**Version :** 1.0  
**Date de dernière mise à jour :** 2024-11-01  
**Responsable du traitement :** ArnaqueRadar (projet pédagogique RNCP)  
**Contact DPO :** contact@arnaqueradar.fr

---

## Conclusion motivée : absence de données personnelles directes

ArnaqueRadar **ne traite pas de données personnelles directes** au sens du RGPD (Règlement UE 2016/679, article 4). Les données collectées et stockées sont exclusivement :

- Des **URLs publiques** signalées comme frauduleuses (domaines, chemins d'accès) ;
- Des **métadonnées agrégées** (type d'arnaque, région administrative, date de signalement) ;
- Des **statistiques** (nombre de signalements, fréquence d'apparition).

Ces données ne permettent pas d'identifier, directement ou indirectement, une personne physique. Elles sont extraites de sources publiques (URLhaus, MalwareTips, CNIL Open Data, PhishStats via Hive) et ne contiennent ni nom, ni prénom, ni adresse e-mail, ni numéro de téléphone, ni adresse IP nominative.

> **En conséquence**, ArnaqueRadar n'est pas soumis à l'obligation de tenir un registre des activités de traitement au titre de l'article 30 du RGPD. Ce registre est produit à titre documentaire pour justifier cette absence.

---

## Tableau des traitements

| Traitement | Données traitées | Base légale (art. 6 RGPD) | Durée de conservation |
|---|---|---|---|
| Collecte des URLs frauduleuses | URLs publiques, type d'arnaque, source | Intérêt légitime (art. 6.1.f) — sécurité numérique du public | 2 ans glissants |
| Stockage en base PostgreSQL | URL, type, région, date signalement | Intérêt légitime | 2 ans glissants |
| Exposition via API REST | Données agrégées anonymisées | Intérêt légitime | Durée de la session JWT (24h) |
| Logs applicatifs | Horodatages, niveaux de log (INFO/WARNING/ERROR) | Intérêt légitime — maintenance et sécurité | 30 jours |
| Authentification API | Identifiants admin (variables d'environnement) | Nécessité contractuelle (art. 6.1.b) | Durée de déploiement |

---

## Procédures de tri et de purge des données

### Procédure automatisée — Mensuelle

Une tâche planifiée (cron) exécute chaque mois la suppression des signalements
dont la date est antérieure à 2 ans. Cette durée est justifiée par la nature
évolutive des arnaques numériques : un signalement vieux de plus de 2 ans
n'a plus de valeur opérationnelle pour la veille.

**Commande SQL de la procédure automatisée :**

```sql
DELETE FROM signalements WHERE date_signalement < NOW() - INTERVAL '2 years';
```

**Exemple de planification cron (Linux) :**

```
0 3 1 * * psql postgresql://admin:secret@localhost/arnaqueradar -c "DELETE FROM signalements WHERE date_signalement < NOW() - INTERVAL '2 years';"
```

### Vérification annuelle manuelle

Une fois par an, le responsable du traitement effectue une revue manuelle :

1. Vérification que la procédure automatisée s'est bien exécutée chaque mois (consultation des logs).
2. Contrôle de la cohérence du volume de données en base (requête `SELECT COUNT(*), MIN(date_signalement) FROM signalements;`).
3. Revue des sources de collecte : vérification que les sources n'ont pas commencé à inclure des données personnelles suite à un changement de format.
4. Mise à jour du présent registre si nécessaire.

---

## Transferts hors UE

ArnaqueRadar peut effectuer des requêtes sortantes vers l'API URLhaus afin de récupérer des indicateurs publics de compromission. Aucun envoi de donnée personnelle directe n'est prévu par ce flux. La localisation effective du traitement dépend néanmoins des conditions du fournisseur utilisé au déploiement.

---

## Droits des personnes

Les données traitées ne permettant pas d'identifier des personnes physiques, les droits RGPD (accès, rectification, effacement, portabilité) ne sont pas applicables. Toute demande peut néanmoins être adressée à contact@arnaqueradar.fr.
