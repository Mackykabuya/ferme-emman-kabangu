import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

// Ces tests lisent le dossier dist : lancer « npm run build » d'abord.
const built = existsSync(new URL('../dist/index.html', import.meta.url));
const read = (p: string) => readFileSync(new URL(`../dist/${p}`, import.meta.url), 'utf8');

test('pages et langues générées', { skip: !built }, () => {
  for (const p of ['index.html', 'en/index.html', 'ln/index.html', 'sw/index.html', 'cultures/index.html', 'contact/index.html', 'actualites/index.html', '404.html', 'sitemap-index.xml']) assert.ok(existsSync(new URL(`../dist/${p}`, import.meta.url)), p);
});
test('hreflang et lang corrects', { skip: !built }, () => {
  const h = read('sw/index.html');
  assert.match(h, /<html lang="sw"/);
  assert.match(h, /hreflang="fr-CD"/);
  assert.match(h, /hreflang="x-default"/);
});
test('une seule balise h1 par page', { skip: !built }, () => {
  for (const p of ['index.html', 'en/cultures/index.html', 'ln/technologie/index.html']) assert.equal((read(p).match(/<h1[ >]/g) ?? []).length, 1, p);
});
test('aucun secret dans la sortie', { skip: !built }, () => {
  assert.doesNotMatch(read('contact/index.html'), /BREVO_API_KEY|xkeysib/);
});
