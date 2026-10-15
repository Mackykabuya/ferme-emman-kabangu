/* Fond de photos qui défilent : lit /photos, enchaîne les images en fondu lent. Sans photo, un fond vert de repli s'affiche. */
(async function () {
  const zone = document.querySelector(".fond");
  if (!zone) return;
  let photos = [];
  try { photos = (await (await fetch("/photos", {cache: "no-store"})).json()).photos || []; } catch (e) {}
  if (!photos.length) { zone.classList.add("sans-photo"); return; }
  zone.classList.add("avec-photos");
  const calques = [0, 1].map(() => { const d = document.createElement("div"); d.className = "diapo"; zone.appendChild(d); return d; });
  const legende = document.querySelector(".legende"), pause = document.querySelector(".pause");
  const reduit = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let i = 0, actif = 1, enPause = reduit, minuteur = null;

  function montrer(k, essais = 0) {
    const img = new Image();
    img.onerror = () => {                                   // photo introuvable ou illisible : on passe à la suivante, et on revient au fond vert si aucune ne s'ouvre
      if (essais + 1 >= photos.length) { zone.classList.remove("avec-photos"); zone.classList.add("sans-photo"); calques.forEach(c => c.classList.remove("on")); return; }
      i = (k + 1) % photos.length; montrer(i, essais + 1);
    };
    img.onload = () => {
      const entrant = calques[1 - actif], sortant = calques[actif];
      entrant.style.backgroundImage = `url("${photos[k].url}")`;
      entrant.classList.remove("zoom"); void entrant.offsetWidth;
      entrant.classList.add("on"); if (!reduit) entrant.classList.add("zoom");
      sortant.classList.remove("on");
      actif = 1 - actif;
      if (legende) legende.textContent = photos[k].nom;
    };
    img.src = photos[k].url;
  }
  function suivante() { if (!enPause) { i = (i + 1) % photos.length; montrer(i); } }
  montrer(0);
  if (photos.length > 1) minuteur = setInterval(suivante, 7000);
  if (pause) {
    pause.textContent = reduit ? "▶" : "❚❚";
    pause.setAttribute("aria-label", reduit ? "Reprendre le défilement des photos" : "Mettre le défilement des photos en pause");
    if (photos.length < 2) pause.style.display = "none";
    pause.onclick = () => {
      enPause = !enPause;
      pause.textContent = enPause ? "▶" : "❚❚";
      pause.setAttribute("aria-label", enPause ? "Reprendre le défilement des photos" : "Mettre le défilement des photos en pause");
    };
  }
})();
