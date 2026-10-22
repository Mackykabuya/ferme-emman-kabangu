# Mettre la ferme en ligne gratuitement : Render + Neon

Render (gratuit) héberge l'application ; Neon (gratuit) garde la base de données, car le disque de Render est effacé à chaque redémarrage.

**Comment ça se comporte :** sans visite pendant 15 minutes, Render endort l'application (la simulation des capteurs s'arrête avec elle) et Neon endort la base 5 minutes plus tard. La première visite suivante prend environ 1 à 2 minutes, puis tout repart. Les données (comptes, parcelles, historique, récoltes) restent dans Neon. C'est adapté aux démonstrations, pas à une exploitation 24 h/24.

## 1. Base de données Neon
1. Créez un compte sur neon.com (sans carte bancaire), puis un projet (région la plus proche de vous).
2. Sur le tableau de bord du projet, cliquez sur « Connect » et copiez l'adresse de connexion, de la forme
   `postgresql://utilisateur:motdepasse@ep-xxxx.neon.tech/neondb?sslmode=require`.

## 2. Application sur Render
1. Poussez le projet sur GitHub (`git add . && git commit -m "..." && git push`).
2. Sur render.com : New → Web Service → connectez GitHub → choisissez le dépôt privé.
3. Réglages : Language = **Docker**, Branch = `main`, Instance Type = **Free**. Laissez le chemin du Dockerfile par défaut.
4. Dans « Environment Variables », ajoutez :

| Nom | Valeur |
|---|---|
| `DATABASE_URL` | l'adresse copiée depuis Neon |
| `DB_POOL` | `3` |
| `ADMIN_MOT_DE_PASSE` | le mot de passe de l'administrateur (8 caractères minimum) |
| `ADMIN_EMAIL` | votre e-mail |
| `FERME_ENV` | `production` |
| `FERME_HTTPS` | `1` |
| `SIMULATION_SECONDES` | `5` |
| `SAUVEGARDE_HEURES` | `0` (Neon garde l'historique de la base ; le disque de Render est effacé) |
| `NOTIF_MINUTES` | `5` (et les `SMTP_*` de votre `.env` si vous voulez les alertes par e-mail) |

5. Cliquez sur « Create Web Service ». La première construction dure plusieurs minutes.
6. Quand le statut passe à « Live », ouvrez l'adresse `https://nom.onrender.com`. Ajoutez ensuite la variable `FERME_URL` avec cette adresse (pour les liens des e-mails) : Render redémarre seul.

## 3. Après la mise en ligne
- Contrôle : `https://nom.onrender.com/health` doit répondre avec « status » ok.
- Connectez-vous avec `ADMIN_EMAIL` (ou `admin`) et `ADMIN_MOT_DE_PASSE`.
- Le https permet l'installation sur le téléphone (PWA) et la géolocalisation de la carte.
- Pour réveiller l'application avant une démonstration, ouvrez le site 2 minutes avant.

## En cas de problème
- **« Out of memory » dans les journaux Render** : le plan gratuit n'a que 512 Mo. Passez à l'offre payante de base, ou hébergez sur une machine plus grande.
- **Erreur de connexion à la base** : vérifiez que `DATABASE_URL` est complète (avec `?sslmode=require`) et sans espace.
- **Le site met longtemps à s'ouvrir** : c'est le réveil normal après 15 minutes d'inactivité.
- **Neon : limite de 100 heures de calcul par mois** : la base ne tourne que quand l'application est éveillée ; avec des démonstrations ponctuelles, la limite n'est pas atteinte.

## E-mails sur Render gratuit
Render gratuit **bloque l'envoi SMTP** (ports 25, 465 et 587) : Gmail ne peut pas servir. Utilisez une API d'e-mail en HTTPS, par exemple Brevo (plan gratuit) :
1. Créez un compte sur brevo.com, validez votre adresse d'expéditeur (Senders), puis créez une clé API (SMTP & API → API Keys).
2. Dans Render, ajoutez : `EMAIL_API=brevo`, `EMAIL_API_CLE=<la clé>`, `EMAIL_DE=Ferme Emman Kabangu <adresse validée>`.
3. Enregistrez : Render redémarre. Testez avec « Envoyer un e-mail de test » dans la page Compte.
(`EMAIL_API=resend` fonctionne aussi.)
