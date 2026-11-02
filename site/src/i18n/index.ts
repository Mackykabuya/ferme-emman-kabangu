import fr from './fr';
import en from './en';
import ln from './ln';
import sw from './sw';

export const locales = ['fr', 'en', 'ln', 'sw'] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = 'fr';

const dictionaries = { fr, en, ln, sw } as const;
export type Dict = typeof fr;

export function isLocale(value: string | undefined): value is Locale {
  return !!value && (locales as readonly string[]).includes(value);
}

export function t(locale: Locale): Dict {
  return dictionaries[locale];
}

/** Chemin public d'une page : le français n'a pas de préfixe. `page` sans slash initial, '' pour l'accueil. */
export function localePath(locale: Locale, page = ''): string {
  const clean = page.replace(/^\/+|\/+$/g, '');
  const prefix = locale === defaultLocale ? '' : `/${locale}`;
  const path = `${prefix}/${clean}`.replace(/\/+$/, '');
  return path === '' ? '/' : path;
}

/** Même page dans une autre langue, à partir du chemin courant. */
export function switchPath(currentPath: string, target: Locale): string {
  const parts = currentPath.split('/').filter(Boolean);
  if (parts.length && isLocale(parts[0]) && parts[0] !== defaultLocale) parts.shift();
  return localePath(target, parts.join('/'));
}

/** Locale déduite du chemin (préfixe), français par défaut. */
export function localeFromPath(currentPath: string): Locale {
  const first = currentPath.split('/').filter(Boolean)[0];
  return isLocale(first) ? first : defaultLocale;
}
