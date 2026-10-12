/* Connexion partagée par toutes les pages : jeton, redirection vers login.html, barre « utilisateur », droits par rôle. */
(function () {
  const CLE = "ferme_session", NIVEAUX = {lecteur: 1, operateur: 2, agronome: 3, admin: 4};
  const lire = () => { try { return JSON.parse(localStorage.getItem(CLE)); } catch (e) { return null; } };
  const ecrire = s => { try { s ? localStorage.setItem(CLE, JSON.stringify(s)) : localStorage.removeItem(CLE); } catch (e) {} };
  const page = location.pathname.split("/").pop() || "";
  const surLogin = ["login.html", "inscription.html", "mot-de-passe-oublie.html", "reinitialiser.html"].includes(page);      // pages publiques
  const versLogin = () => { ecrire(null); if (!surLogin) location.replace("login.html" + (/^[a-z]+\.html$/.test(page) ? "?retour=" + page : "")); };

  let session = lire();
  const _fetch = window.fetch.bind(window);
  window.fetch = async (url, init) => {
    const u = typeof url === "string" ? url : "";
    const interne = u && new URL(u, location.href).origin === location.origin && !u.includes("/auth/connexion");
    if (interne && session) init = {...(init || {}), headers: {...((init && init.headers) || {}), Authorization: "Bearer " + session.jeton}};
    const r = await _fetch(url, init);
    if (r.status === 401 && interne) versLogin();
    return r;
  };

  const Ferme = window.Ferme = {
    utilisateur: () => session && session.utilisateur,
    peut: role => !!(session && NIVEAUX[session.utilisateur.role] >= NIVEAUX[role]),
    /* cache un bouton ou un bloc réservé à un rôle supérieur (le serveur refuse de toute façon) */
    reserver(el, role) { if (!Ferme.peut(role)) el.hidden = true; return el; },
    ouvrirSession(rep) { session = {jeton: rep.jeton, utilisateur: rep.utilisateur}; ecrire(session); },
    async deconnecter() { try { await _fetch("/auth/deconnexion", {method: "POST", headers: {Authorization: "Bearer " + session.jeton}}); } catch (e) {} versLogin(); },
  };

  if (surLogin) return;
  if (!session) { versLogin(); return; }
  document.documentElement.setAttribute("data-role", session.utilisateur.role);
  const css = document.createElement("style");
  css.textContent = ("header{position:relative}.ferme-session{position:absolute;top:10px;right:16px;margin:0;font-size:.85rem;color:inherit}.ferme-session a,.ferme-session button{color:inherit;margin-left:10px;background:none;border:0;padding:0;font:inherit;text-decoration:underline;cursor:pointer}@media(max-width:700px){.ferme-session{position:static;padding:6px 16px}}");
  document.head.appendChild(css);

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-min-role]").forEach(e => Ferme.reserver(e, e.dataset.minRole));
    const h = document.querySelector("header");
    if (h) {
      const p = document.createElement("p"); p.className = "ferme-session";
      const u = session.utilisateur;
      p.append(`${u.nom} · ${u.role_libelle}`);
      const compte = document.createElement("a"); compte.href = "compte.html"; compte.textContent = u.role === "admin" ? "Comptes" : "Mon compte";
      const sortir = document.createElement("button"); sortir.type = "button"; sortir.textContent = "Se déconnecter"; sortir.onclick = Ferme.deconnecter;
      p.append(compte, sortir); h.appendChild(p);
      if (u.role === "admin") _fetch("/auth/demandes", {headers: {Authorization: "Bearer " + session.jeton}}).then(r => r.ok ? r.json() : []).then(l => { if (l.length) compte.textContent = `Comptes (${l.length} demande${l.length > 1 ? "s" : ""})`; }).catch(() => {});
    }
    _fetch("/auth/moi", {headers: {Authorization: "Bearer " + session.jeton}}).then(r => {      // le rôle a pu changer depuis la connexion
      if (r.status === 401) return versLogin();
      return r.json().then(m => { if (m.role !== session.utilisateur.role) { session.utilisateur = m; ecrire(session); location.reload(); } });
    }).catch(() => {});
  });
})();
