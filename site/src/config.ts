/**
 * Réglages du site à adapter. Tout ce qui est vide est simplement masqué sur le site.
 */
export const config = {
  name: 'Ferme Emman Kabangu',
  /** Adresse du tableau de bord de la ferme (application de gestion, hébergée sur Render). */
  appUrl: 'https://ferme-emman-kabangu.onrender.com',
  /** Lieu affiché dans le pied de page et le formulaire de contact. */
  location: { fr: 'Kinshasa, République démocratique du Congo', en: 'Kinshasa, Democratic Republic of the Congo' },
  /** Numéro WhatsApp au format international, chiffres seulement, sans + ni espaces (ex. 243810000000). Vide = bouton masqué. */
  whatsapp: '',
  /** Téléphone affiché (ex. +243 81 000 00 00). Vide = masqué. */
  phone: '',
  /** Adresse e-mail affichée publiquement. Vide = masquée (le formulaire de contact reste disponible). */
  email: '',
  /** Clé publique Cloudflare Turnstile (anti-spam du formulaire). Vide = pas de contrôle anti-robot visible. */
  turnstileSiteKey: import.meta.env.PUBLIC_TURNSTILE_SITEKEY ?? '',
};
