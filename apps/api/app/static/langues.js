/* Langues de l'interface : français (par défaut), anglais, lingala, swahili.
   Le texte des pages reste écrit en français ; ce script le remplace à l'affichage par la traduction trouvée dans
   langues-dict.js (aussi pour les textes ajoutés après coup par les pages). Un texte sans traduction reste en français.
   Les conseils générés par le serveur (diagnostic détaillé, alertes) restent en français pour l'instant. */
(function () {
  const CLE = "ferme_langue", LANGUES = {fr: "Français", en: "English", ln: "Lingála", sw: "Kiswahili"}, IDX = {en: 0, ln: 1, sw: 2};
  const DICT = window.FERME_DICT || {};
  let lang = "fr";
  try { const l = localStorage.getItem(CLE); if (LANGUES[l]) lang = l; } catch (e) {}

  const norm = s => s.replace(/\s+/g, " ").trim();
  function traduire(fr) {                                   // « texte français » -> texte dans la langue choisie (sinon inchangé)
    if (lang === "fr") return fr;
    const cle = norm(fr), e = DICT[cle];
    if (e && e[IDX[lang]]) return e[IDX[lang]];
    const m = cle.match(/^(\d+(?:[.,]\d+)?)\s+(.+)$/);       // « 3 ont besoin d'eau · » : le nombre reste, le reste se traduit
    if (m && DICT[m[2]] && DICT[m[2]][IDX[lang]]) return m[1] + " " + DICT[m[2]][IDX[lang]];
    return fr;
  }
  const garder = (fr, tr) => { const d = fr.match(/^\s*/)[0], f = fr.match(/\s*$/)[0]; return d + tr.trim() + f; };

  const mem = new WeakMap(), ATTR = ["placeholder", "title", "aria-label", "alt"];
  function texte(n) {
    let o = mem.get(n);
    if (!o || n.nodeValue !== o.vu) o = {fr: n.nodeValue, vu: n.nodeValue};      // nouveau texte, ou texte réécrit par la page
    const t = traduire(o.fr), v = t === o.fr ? o.fr : garder(o.fr, t);
    if (n.nodeValue !== v) n.nodeValue = v;
    o.vu = v; mem.set(n, o);
  }
  function element(el) {
    let o = mem.get(el) || {};
    for (const a of ATTR) {
      const cur = el.getAttribute(a);
      if (cur === null) continue;
      if (!o[a] || cur !== o[a].vu) o[a] = {fr: cur, vu: cur};
      const t = traduire(o[a].fr);
      if (cur !== t) el.setAttribute(a, t);
      o[a].vu = t;
    }
    mem.set(el, o);
  }
  const IGNORE = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE"]);
  function parcourir(racine) {
    if (!racine) return;
    if (racine.nodeType === 3) { if (!IGNORE.has(racine.parentNode && racine.parentNode.nodeName)) texte(racine); return; }
    if (racine.nodeType !== 1 || IGNORE.has(racine.nodeName) || racine.closest("[data-no-i18n]")) return;
    element(racine);
    const w = document.createTreeWalker(racine, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (n.nodeType === 3) { if (!IGNORE.has(n.parentNode.nodeName)) texte(n); }
      else if (!IGNORE.has(n.nodeName) && !n.hasAttribute("data-no-i18n")) element(n);
    }
  }
  let titreFr = null, vuTitre = null;
  function titre() {
    if (titreFr === null || document.title !== vuTitre) titreFr = document.title;
    const t = traduire(titreFr); vuTitre = t; if (document.title !== t) document.title = t;
  }
  let obs = null;
  function appliquer() {
    document.documentElement.lang = lang;
    titre(); parcourir(document.body);
    if (!obs && document.body) {
      obs = new MutationObserver(muts => {
        for (const m of muts) {
          if (m.type === "childList") m.addedNodes.forEach(parcourir);
          else if (m.type === "characterData") parcourir(m.target);
          else if (m.type === "attributes") element(m.target);
        }
        titre();
      });
      obs.observe(document.body, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTR});
    }
  }

  function choisir(l) {
    if (!LANGUES[l]) return;
    lang = l;
    try { localStorage.setItem(CLE, l); } catch (e) {}
    appliquer();
  }
  window.Ferme = Object.assign(window.Ferme || {}, {t: traduire, langue: () => lang, choisirLangue: choisir});
  window.T = traduire;

  function selecteur() {
    const s = document.createElement("select");
    s.setAttribute("data-no-i18n", ""); s.setAttribute("aria-label", "Langue / Language");
    s.style.cssText = "position:fixed;left:12px;bottom:12px;z-index:9999;padding:6px 10px;border-radius:99px;border:1px solid rgba(0,0,0,.25);background:rgba(255,255,255,.94);color:#17301f;font:600 .85rem system-ui,sans-serif;box-shadow:0 2px 10px #0003;cursor:pointer";
    for (const [k, v] of Object.entries(LANGUES)) { const o = document.createElement("option"); o.value = k; o.textContent = "🌐 " + v; if (k === lang) o.selected = true; s.appendChild(o); }
    s.onchange = () => choisir(s.value);
    document.body.appendChild(s);
  }
  document.addEventListener("DOMContentLoaded", () => { selecteur(); if (lang !== "fr") appliquer(); else appliquer(); });
})();
