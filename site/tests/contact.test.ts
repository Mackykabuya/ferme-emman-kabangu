import test from 'node:test';
import assert from 'node:assert/strict';
import { handle } from '../functions/api/contact.ts';

const env = { BREVO_API_KEY: 'k', CONTACT_TO: 'a@b.cd', CONTACT_FROM: 'c@d.ef' };
const req = (body: unknown, headers: Record<string, string> = {}) =>
  new Request('https://site.test/api/contact', { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify(body) });
const ok = { name: 'Awa', how: 'awa@x.org', message: 'Bonjour <b>', subject: 'achat' };

test('envoie le message et échappe le HTML', async () => {
  let sent: any;
  const f = (async (_u: string, init: any) => { sent = JSON.parse(init.body); return new Response('{}', { status: 201 }); }) as any;
  const r = await handle(req(ok), env, f);
  assert.equal(r.status, 200);
  assert.ok(sent.htmlContent.includes('&lt;b&gt;'));
  assert.equal(sent.replyTo.email, 'awa@x.org');
});
test('pot de miel : réponse ok sans envoi', async () => {
  let called = false;
  const f = (async () => { called = true; return new Response('{}'); }) as any;
  const r = await handle(req({ ...ok, website: 'http://spam' }), env, f);
  assert.equal(r.status, 200); assert.equal(called, false);
});
test('refuse une autre origine', async () => {
  const r = await handle(req(ok, { origin: 'https://evil.test' }), env, (async () => new Response('{}')) as any);
  assert.equal(r.status, 403);
});
test('champs manquants', async () => {
  const r = await handle(req({ ...ok, message: '' }), env, (async () => new Response('{}')) as any);
  assert.equal(r.status, 400);
});
test('Turnstile requis si secret défini', async () => {
  const r = await handle(req(ok), { ...env, TURNSTILE_SECRET: 's' }, (async () => new Response('{}')) as any);
  assert.equal(r.status, 400);
  assert.equal((await r.json()).error, 'human');
});
test('Brevo en erreur → 502', async () => {
  const r = await handle(req(ok), env, (async () => new Response('x', { status: 401 })) as any);
  assert.equal(r.status, 502);
});
test('GET refusé', async () => {
  const r = await handle(new Request('https://site.test/api/contact'), env);
  assert.equal(r.status, 405);
});
