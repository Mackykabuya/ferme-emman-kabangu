/* Application installable : enregistre le service worker et garde la proposition d'installation du navigateur
   (bouton « Installer » dans Mon compte). Sans effet, sans erreur, si le navigateur ne sait pas faire (HTTP simple, vieux navigateur). */
(function () {
  window.FermePWA = {proposition: null, installee: matchMedia("(display-mode: standalone)").matches || navigator.standalone === true};
  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
    window.addEventListener("load", () => navigator.serviceWorker.register("/tableau-de-bord/sw.js", {scope: "/tableau-de-bord/"}).catch(() => {}));
  }
  window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); FermePWA.proposition = e; document.dispatchEvent(new Event("ferme-pwa")); });
  window.addEventListener("appinstalled", () => { FermePWA.proposition = null; FermePWA.installee = true; document.dispatchEvent(new Event("ferme-pwa")); });
  FermePWA.installer = async () => {
    const p = FermePWA.proposition; if (!p) return false;
    p.prompt(); const r = await p.userChoice; FermePWA.proposition = null; document.dispatchEvent(new Event("ferme-pwa"));
    return r.outcome === "accepted";
  };
})();
