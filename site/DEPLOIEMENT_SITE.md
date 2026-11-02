# Site public : déploiement sur Cloudflare Pages (gratuit)

Le site est dans le dossier `site/` du dépôt. Il est indépendant de l'application de gestion (Render).

## 1. Tester en local (facultatif)
```bash
cd site
npm install
npm run dev        # http://localhost:4321
npm test           # tests (lancer « npm run build » avant pour les tests de sortie)
```
Node 22 ou plus est requis.

## 2. Créer le projet Cloudflare Pages
1. Créez un compte sur https://dash.cloudflare.com (gratuit).
2. **Workers & Pages** → **Create** → onglet **Pages** → **Connect to Git** → choisissez le dépôt `ferme-emman-kabangu`.
3. Réglages de build :
   - **Production branch** : `main`
   - **Root directory** : `site`
   - **Build command** : `npm run build`
   - **Build output directory** : `dist`
   - **Environment variable** : `NODE_VERSION` = `22`
4. **Save and Deploy**. Le site est publié sur `https://<nom-du-projet>.pages.dev`.
5. Si le nom du projet n'est pas `ferme-emman-kabangu`, ajoutez la variable `SITE_URL` = votre adresse `https://...pages.dev` (utile pour le plan du site et les liens de partage), puis redéployez.

## 3. Activer le formulaire de contact
Dans le projet Pages : **Settings → Variables and secrets** (environnement Production), ajoutez en type **Secret** :

| Nom | Valeur |
|---|---|
| `BREVO_API_KEY` | une clé API Brevo (créez-en une nouvelle, ne réutilisez pas celle de Render) |
| `CONTACT_TO` | l'adresse qui reçoit les messages |
| `CONTACT_FROM` | l'expéditeur validé dans Brevo (kabuyamacky8@gmail.com) |

Puis **Deployments → Retry deployment**. Ne collez jamais ces valeurs dans GitHub ni dans une conversation.

Anti-spam : un champ piège invisible et un contrôle d'origine sont déjà actifs. Pour ajouter Cloudflare Turnstile (gratuit) : créez un widget Turnstile, mettez la clé publique dans `PUBLIC_TURNSTILE_SITEKEY` et la clé secrète dans `TURNSTILE_SECRET`.

## 4. Personnaliser
- `site/src/config.ts` : numéro WhatsApp, téléphone, e-mail public (vide = masqué).
- `site/src/i18n/*.ts` : tous les textes. **Le lingala (`ln.ts`) doit être relu par un locuteur natif** ; les noms de cultures en lingala sont dans `src/data/crops.ts`.
- `site/src/content/news/fr|en/*.md` : ajoutez un fichier pour publier une actualité (les langues sans traduction affichent la version française avec une note).
- Photos : à ajouter plus tard dans `site/src/assets/photos` (la galerie n'est pas encore affichée tant qu'il n'y a pas de photos réelles).
- Adresse de l'application : `appUrl` dans `config.ts`.

## 5. Éviter de redéployer Render pour rien
Dans Render : service → **Settings → Build & Deploy → Build Filters** → **Ignored Paths** : `site/**`.

## 6. Plus tard : un nom de domaine
Achetez un domaine, puis Pages → **Custom domains**. Changez `SITE_URL`. Un domaine améliore aussi la réception des e-mails Brevo.
