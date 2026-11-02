/**
 * Cloudflare Pages Function : POST /api/contact
 * Envoie le message du formulaire par e-mail via l'API HTTPS de Brevo.
 * Variables (secrets) à définir dans Cloudflare Pages : BREVO_API_KEY, CONTACT_TO, CONTACT_FROM ; optionnel : TURNSTILE_SECRET.
 */
export interface Env {
  BREVO_API_KEY?: string;
  CONTACT_TO?: string;
  CONTACT_FROM?: string;
  TURNSTILE_SECRET?: string;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });

const clean = (v: unknown, max: number) => (typeof v === 'string' ? v.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').trim().slice(0, max) : '');
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

export async function handle(request: Request, env: Env, fetchImpl: typeof fetch = fetch): Promise<Response> {
  if (request.method !== 'POST') return json({ error: 'method' }, 405);

  // Même origine uniquement
  const origin = request.headers.get('origin');
  if (origin && origin !== new URL(request.url).origin) return json({ error: 'origin' }, 403);

  let data: Record<string, unknown>;
  try { data = await request.json(); } catch { return json({ error: 'json' }, 400); }

  // Pot de miel : un robot remplit ce champ caché. On répond « ok » sans rien envoyer.
  if (clean(data.website, 200)) return json({ ok: true });

  const name = clean(data.name, 100);
  const how = clean(data.how, 150);
  const message = clean(data.message, 3000);
  const subject = clean(data.subject, 30) || 'autre';
  if (!name || !how || !message) return json({ error: 'field' }, 400);

  if (env.TURNSTILE_SECRET) {
    const token = clean(data['cf-turnstile-response'], 2048);
    if (!token) return json({ error: 'human' }, 400);
    const r = await fetchImpl('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
      method: 'POST',
      body: new URLSearchParams({ secret: env.TURNSTILE_SECRET, response: token, remoteip: request.headers.get('cf-connecting-ip') ?? '' }),
    });
    const v = (await r.json().catch(() => ({}))) as { success?: boolean };
    if (!v.success) return json({ error: 'human' }, 400);
  }

  if (!env.BREVO_API_KEY || !env.CONTACT_TO || !env.CONTACT_FROM) return json({ error: 'config' }, 500);

  const looksLikeEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(how);
  const payload: Record<string, unknown> = {
    sender: { name: 'Site Ferme Emman Kabangu', email: env.CONTACT_FROM },
    to: [{ email: env.CONTACT_TO }],
    subject: `[Site] ${subject} — ${name}`.slice(0, 200),
    htmlContent: `<p><b>Nom :</b> ${esc(name)}</p><p><b>Contact :</b> ${esc(how)}</p><p><b>Sujet :</b> ${esc(subject)}</p><p>${esc(message).replace(/\n/g, '<br>')}</p>`,
  };
  if (looksLikeEmail) payload.replyTo = { email: how, name };

  const res = await fetchImpl('https://api.brevo.com/v3/smtp/email', {
    method: 'POST',
    headers: { 'api-key': env.BREVO_API_KEY, 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) return json({ error: 'send' }, 502);
  return json({ ok: true });
}

export const onRequest = (ctx: { request: Request; env: Env }) => handle(ctx.request, ctx.env);
