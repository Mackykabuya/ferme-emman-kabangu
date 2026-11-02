import test from 'node:test';
import assert from 'node:assert/strict';
import fr from '../src/i18n/fr.ts';
import en from '../src/i18n/en.ts';
import ln from '../src/i18n/ln.ts';
import sw from '../src/i18n/sw.ts';

const shape = (v: unknown, p = ''): string[] =>
  Array.isArray(v) ? [`${p}[${v.length}]`, ...v.flatMap((x, i) => shape(x, `${p}[${i}]`))]
  : v && typeof v === 'object' ? Object.entries(v).flatMap(([k, x]) => shape(x, p ? `${p}.${k}` : k))
  : [p];

for (const [name, d] of Object.entries({ en, ln, sw })) {
  test(`${name} a les mêmes clés que fr`, () => assert.deepEqual(shape(d), shape(fr)));
  test(`${name} n'a pas de texte vide`, () => {
    const empties = JSON.stringify(d).includes('""');
    assert.equal(empties, false);
  });
}
test('le message de commande garde {crop}', () => {
  for (const d of [fr, en, ln, sw]) assert.ok(d.cropsPage.orderMessage.includes('{crop}'));
});
