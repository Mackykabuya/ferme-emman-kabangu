/* Photos des cultures, partagées par les pages de travail : « Maïs » ↔ 01-mais.jpg, « Banane/Plantain » ↔ plantain.jpg. */
const photosPromise = fetch("/photos").then(r => r.json()).then(d => d.photos || []).catch(() => []);
const norm = t => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
/* Une photo est associée à une culture si son nom contient un mot du nom de la plante (« Plantain » pour « Banane/Plantain »). */
function photoDe(plante, photos) {
  const mots = norm(plante).split(/[^a-z]+/).filter(m => m.length > 2);
  return photos.find(ph => { const n = norm(ph.nom); return mots.some(m => n.includes(m) || m.includes(n)); });
}
/* Bandeau des pages de travail : ajoute la couche photo derrière l'en-tête (les photos viennent de /photos, comme sur l'accueil). */
document.addEventListener("DOMContentLoaded", () => {
  const h = document.querySelector("header");
  if (!h) return;
  const fond = document.createElement("div"), voile = document.createElement("div");
  fond.className = "fond"; voile.className = "voile";
  fond.setAttribute("aria-hidden", "true"); voile.setAttribute("aria-hidden", "true");
  h.prepend(fond, voile);
  const s = document.createElement("script"); s.src = "fond.js"; document.body.appendChild(s);
});
