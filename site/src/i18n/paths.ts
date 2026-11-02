import { locales, defaultLocale, type Locale } from './index';

/** getStaticPaths commun : fr sans préfixe (locale undefined), les autres avec préfixe. */
export function localeStaticPaths() {
  return locales.map((l) => ({ params: { locale: l === defaultLocale ? undefined : l }, props: { locale: l as Locale } }));
}
