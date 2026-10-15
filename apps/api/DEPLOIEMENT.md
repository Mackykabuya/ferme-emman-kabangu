# Mise en service — Ferme Emman Kabangu

Les capteurs restent **simulés** (`SIMULATION_SECONDES` > 0). Ce guide rend l'application sûre et durable ; les vrais capteurs (MQTT, clés d'appareil) viendront plus tard.

> Les fichiers Docker/Caddy n'ont pas pu être testés dans l'environnement de développement (pas de démon Docker). Le code, lui, est testé sur SQLite et PostgreSQL.

## Ce qui est nouveau (étape 18)
- **Sauvegardes** automatiques (toutes les 24 h, 14 copies) dans `apps/api/sauvegardes/`, et bouton « Sauvegarder maintenant » + téléchargement dans la page *Mon compte* (administrateur).
- **Fichier `.env`** lu automatiquement (`apps/api/.env`) — voir `.env.example`.
- **En-têtes de sécurité**, pas de cache sur les données, documentation `/docs` coupée si `FERME_ENV=production`.
- **`/health`** vérifie la base (503 si elle ne répond pas).

## Option A — Sur votre PC (WSL), sans Docker
1. Dans `apps/api`, créez `.env` :
   ```
   ADMIN_MOT_DE_PASSE=une-longue-phrase
   SIMULATION_SECONDES=5
   ```
2. Lancez : `uvicorn app.main:app --host 0.0.0.0 --port 8000` (un seul worker, ne pas ajouter `--workers`).
3. Autres appareils du même réseau : `http://IP-DU-PC:8000`. Avec WSL2 il faut soit le réseau « mirrored » (`.wslconfig` : `[wsl2]` / `networkingMode=mirrored`), soit, dans PowerShell administrateur :
   `netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=<IP de wsl hostname -I>`
   puis `New-NetFirewallRule -DisplayName Ferme -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`.

## Option B — Serveur (VPS) avec Docker + HTTPS
1. Pointez un nom de domaine vers l'IP du serveur ; ouvrez les ports 80 et 443.
2. Copiez le projet, puis `cp .env.example .env` et remplissez `FERME_DOMAINE`, `POSTGRES_PASSWORD`, `ADMIN_MOT_DE_PASSE`.
3. `docker compose up -d --build` (les modèles sont entraînés à la construction).
4. Ouvrez `https://votre-domaine`. Journaux : `docker compose logs -f api`.
Vos photos (`apps/api/app/static/photos`) et `site.json` sont montés dans le conteneur.

## Connexion par e-mail et mot de passe oublié
- On se connecte avec son **e-mail** et son mot de passe (un ancien identifiant comme « admin » marche encore). L'inscription demande un e-mail.
- Votre compte administrateur existant n'a pas d'e-mail : ajoutez `ADMIN_EMAIL=vous@exemple.com` dans `apps/api/.env` (il est appliqué au démarrage), ou ajoutez-le dans *Mon compte*.
- « Mot de passe oublié ? » envoie un lien valable 60 min, utilisable une seule fois. Pour envoyer de vrais e-mails, renseignez `SMTP_HOTE`, `SMTP_PORT`, `SMTP_UTILISATEUR`, `SMTP_MOT_DE_PASSE`, `SMTP_DE` **et** `FERME_URL` (par ex. `http://192.168.1.25:8000`).
- **Sans SMTP** (cas simple à la maison) : le lien s'écrit dans le terminal du serveur, et l'administrateur peut cliquer sur « Lien de réinitialisation » dans *Mon compte > Comptes utilisateurs* pour le donner à la personne.
- Pour Gmail : activez la validation en 2 étapes, créez un « mot de passe d'application », et utilisez `SMTP_HOTE=smtp.gmail.com`, `SMTP_PORT=587`, votre adresse Gmail comme `SMTP_UTILISATEUR`.

## Sauvegardes et restauration
- Liste / création : page *Mon compte*, ou `python -m app.sauvegarde lister` / `sauvegarder` (depuis `apps/api`).
- Restaurer : arrêter le serveur, `python -m app.sauvegarde restaurer ferme-AAAAMMJJ-HHMMSS.db` (une copie de sécurité est faite avant).
- Docker : `docker compose exec api python -m app.sauvegarde restaurer <fichier>` puis `docker compose restart api`.
- Copiez de temps en temps les sauvegardes **hors du serveur** (clé USB, autre machine).

## Variables utiles
`DATABASE_URL`, `ADMIN_MOT_DE_PASSE`, `FERME_ENV=production`, `FERME_HTTPS=1`, `FERME_DOCS=1`, `SIMULATION_SECONDES`, `SAUVEGARDE_HEURES` (0 = coupé), `SAUVEGARDE_GARDER`, `SAUVEGARDES_DOSSIER`, `SESSION_HEURES`.

## Plus tard : vrais capteurs
Passer `SIMULATION_SECONDES=0`, puis ajouter la réception des mesures (MQTT/HTTP) avec une clé par appareil.
