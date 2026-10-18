/* Service worker de l'application installable.
   Règle simple : le réseau d'abord (on voit toujours la dernière version quand on est connecté), et une copie en
   mémoire seulement pour les pages et fichiers de l'interface quand le réseau est coupé. Les données de la ferme
   (API : parcelles, alertes, comptes…) ne sont JAMAIS gardées en mémoire. Changez VERSION pour vider l'ancienne copie. */
const VERSION = "ferme-v1", CHEMIN = "/tableau-de-bord/";
const COQUILLE = ["offline.html", "marque.css", "tableau.css", "public.css", "auth.js", "langues.js", "langues-dict.js", "tableau.js", "pwa.js",
                  "logo.png", "logo-icone.png", "icon-192.png", "login.html", "parcelles.html"].map(f => CHEMIN + f);

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => Promise.allSettled(COQUILLE.map(u => c.add(u)))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== "GET" || u.origin !== location.origin || !u.pathname.startsWith(CHEMIN) || u.pathname === CHEMIN + "sw.js") return;   // API et le reste : intouchés
  e.respondWith((async () => {
    try {
      const rep = await fetch(r);
      if (rep.ok && rep.type === "basic") { const c = await caches.open(VERSION); c.put(r, rep.clone()); }
      return rep;
    } catch (err) {
      const copie = await caches.match(r, {ignoreSearch: true});
      if (copie) return copie;
      if (r.mode === "navigate") return (await caches.match(CHEMIN + "offline.html")) || Response.error();
      return Response.error();
    }
  })());
});
