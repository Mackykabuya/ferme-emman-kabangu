import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import tailwindcss from '@tailwindcss/vite';

// Adresse publique du site (sert au plan du site, aux liens canoniques et aux aperçus de partage).
// Changez-la ici, ou avec la variable SITE_URL, quand vous aurez un nom de domaine.
const site = process.env.SITE_URL || 'https://ferme-emman-kabangu.pages.dev';

export default defineConfig({
  site,
  trailingSlash: 'ignore',
  i18n: {
    defaultLocale: 'fr',
    locales: ['fr', 'en', 'ln', 'sw'],
    routing: { prefixDefaultLocale: false },
  },
  integrations: [
    sitemap({
      i18n: { defaultLocale: 'fr', locales: { fr: 'fr-CD', en: 'en', ln: 'ln', sw: 'sw' } },
    }),
  ],
  vite: { plugins: [tailwindcss()] },
});
