/* Carte Vélo France — recherche de ville, commune à la carte et aux statistiques.

   Utilisation :
     var r = RechercheVille.attacher(champ, liste, function (ville) { ... });
     r.afficher("Clermont-Ferrand");        // texte affiché dans le champ
     RechercheVille.trouver("63113").then(function (ville) { ... });

   ville = { code, nom, codesPostaux, population, entiere }
     - entiere : code de la commune entière pour un arrondissement de Paris, Lyon ou Marseille
       (vide pour une commune). L'adresse utilise alors ?ville=<entiere>&arr=<code>.

   Liste précalculée : data/communes-index.json (chargée au premier usage).
*/
(function () {
  "use strict";

  var promesseIndex = null;

  function index() {
    if (!promesseIndex) {
      promesseIndex = fetch("data/communes-index.json").then(function (r) {
        if (!r.ok) throw new Error("index " + r.status);
        return r.json();
      }).then(function (d) {
        return d.communes.map(function (l) {
          return { code: l[0], nom: l[1], codesPostaux: l[2], population: l[3], entiere: l[4] || "",
                   cle: normaliser(l[1]) };
        });
      });
      promesseIndex.catch(function () { promesseIndex = null; });
    }
    return promesseIndex;
  }

  /* « Saint-Étienne » -> « saint etienne » ; « St Etienne » -> « saint etienne » */
  function normaliser(t) {
    return String(t).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
      .replace(/[-'’_.,]/g, " ").replace(/\bste\b/g, "sainte").replace(/\bst\b/g, "saint")
      .replace(/\s+/g, " ").trim();
  }

  function rechercher(liste, texte, max) {
    var q = normaliser(texte);
    if (!q) return [];
    var res = [];
    if (/^\d{2,5}$/.test(q)) {
      // Code postal (ou début), ou code INSEE exact
      liste.forEach(function (v) {
        if (v.code === q || v.codesPostaux.split(" ").some(function (cp) { return cp.indexOf(q) === 0; })) res.push(v);
      });
    } else {
      var debut = [], mot = [], dedans = [];
      liste.forEach(function (v) {
        if (v.cle.indexOf(q) === 0) debut.push(v);
        else if (v.cle.indexOf(" " + q) >= 0) mot.push(v);
        else if (q.length >= 3 && v.cle.indexOf(q) >= 0) dedans.push(v);
      });
      res = debut.concat(mot, dedans);   // l'index est déjà trié par population décroissante
    }
    return res.slice(0, max || 8);
  }

  function trouver(code) {
    return index().then(function (liste) {
      return liste.find(function (v) { return v.code === code; }) || null;
    });
  }

  function attacher(champ, liste, surChoix) {
    var resultats = [], actif = -1, idListe = liste.id;
    champ.setAttribute("role", "combobox");
    champ.setAttribute("aria-autocomplete", "list");
    champ.setAttribute("aria-expanded", "false");
    champ.setAttribute("aria-controls", idListe);
    champ.setAttribute("autocomplete", "off");
    liste.setAttribute("role", "listbox");
    liste.hidden = true;

    function fermer() {
      liste.hidden = true; actif = -1;
      champ.setAttribute("aria-expanded", "false");
      champ.removeAttribute("aria-activedescendant");
    }

    function dessiner() {
      liste.innerHTML = "";
      if (!resultats.length) {
        var vide = document.createElement("li");
        vide.className = "aucun"; vide.setAttribute("role", "option"); vide.setAttribute("aria-disabled", "true");
        vide.textContent = "Aucune commune ne correspond.";
        liste.appendChild(vide);
      }
      resultats.forEach(function (v, i) {
        var li = document.createElement("li");
        li.id = idListe + "-" + i;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", i === actif ? "true" : "false");
        var nom = document.createElement("span"); nom.className = "nom"; nom.textContent = v.nom;
        var info = document.createElement("span"); info.className = "info";
        info.textContent = (v.codesPostaux ? v.codesPostaux.split(" ").slice(0, 3).join(", ") : v.code) +
          (v.population ? ", " + new Intl.NumberFormat("fr-FR").format(v.population) + " hab." : "");
        li.appendChild(nom); li.appendChild(info);
        li.addEventListener("mousedown", function (e) { e.preventDefault(); choisir(i); });
        liste.appendChild(li);
      });
      liste.hidden = false;
      champ.setAttribute("aria-expanded", "true");
      if (actif >= 0) champ.setAttribute("aria-activedescendant", idListe + "-" + actif);
      else champ.removeAttribute("aria-activedescendant");
    }

    function choisir(i) {
      var v = resultats[i];
      if (!v) return;
      champ.value = v.nom;
      fermer();
      surChoix(v);
    }

    champ.addEventListener("focus", function () { index().catch(function () {}); });
    champ.addEventListener("input", function () {
      var texte = champ.value;
      if (normaliser(texte).length < 2) { fermer(); return; }
      index().then(function (l) {
        if (champ.value !== texte) return;      // l'utilisateur a continué à taper
        resultats = rechercher(l, texte, 8); actif = resultats.length ? 0 : -1; dessiner();
      }).catch(function () {
        resultats = []; liste.innerHTML = '<li class="aucun" role="option" aria-disabled="true">Liste des communes indisponible.</li>';
        liste.hidden = false;
      });
    });
    champ.addEventListener("keydown", function (e) {
      if (liste.hidden && e.key !== "ArrowDown") { if (e.key === "Escape") champ.value = ""; return; }
      if (e.key === "ArrowDown") { e.preventDefault(); if (resultats.length) { actif = (actif + 1) % resultats.length; dessiner(); } }
      else if (e.key === "ArrowUp") { e.preventDefault(); if (resultats.length) { actif = (actif - 1 + resultats.length) % resultats.length; dessiner(); } }
      else if (e.key === "Enter") { e.preventDefault(); choisir(actif < 0 ? 0 : actif); }
      else if (e.key === "Escape") { fermer(); }
    });
    champ.addEventListener("blur", function () { setTimeout(fermer, 100); });

    return { afficher: function (texte) { champ.value = texte || ""; } };
  }

  /* Code du département d'un code INSEE */
  function departement(code) {
    if (!code) return "";
    var d = code.slice(0, 2);
    return d === "97" ? code.slice(0, 3) : d;
  }

  window.RechercheVille = { attacher: attacher, trouver: trouver, departement: departement,
                            rechercher: rechercher, normaliser: normaliser, index: index };
})();
