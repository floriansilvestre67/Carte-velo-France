/* Carte Vélo France — logique de la carte.
   Les données sont produites chaque jour par scripts/construire_donnees.py :
     data/meta.json             description des indicateurs, statut des sources, date
     data/departements.geojson  contours + chiffres de chaque département
     data/stations.json         stations VLS (chargées seulement si le calque est activé)
*/
(function () {
  "use strict";

  // Palette séquentielle (5 classes) : du vert très clair au vert foncé.
  var COULEURS = ["#e3f2ea", "#a8d8bf", "#5fb592", "#21885f", "#0b5a40"];
  var COULEUR_INDISPO = "#c9cfcc";
  var NB_CLASSES = COULEURS.length;

  var etat = {
    meta: null,
    geo: null,
    indicateur: "score",
    selection: null,     // code du département affiché dans la fiche
    region: null,        // code de la région filtrée (null = toute la France)
    ville: null,         // code INSEE de la ville choisie (commune entière)
    arr: null,           // arrondissement éventuel (Paris, Lyon, Marseille)
    calqueVille: null,   // contour de la ville
    anneeVille: null,    // année choisie dans la fiche Ville
    partie: "haut",      // onglet du classement
    seuils: [],
    couches: {},         // code -> couche Leaflet
    calqueDeps: null,
    calqueVLS: null,
    calqueCyclOSM: null
  };

  var $ = function (id) { return document.getElementById(id); };

  // ---------------------------------------------------------------- formats

  function indicateur(cle) {
    return etat.meta.indicateurs.find(function (i) { return i.cle === cle; });
  }

  function formater(valeur, cle) {
    if (valeur === null || valeur === undefined) return null;
    var ind = indicateur(cle);
    var d = ind ? ind.decimales : 1;
    return new Intl.NumberFormat("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d }).format(valeur);
  }

  function avecUnite(valeur, cle) {
    var texte = formater(valeur, cle);
    if (texte === null) return null;
    var u = indicateur(cle).unite;
    return u === "/ 100" ? texte + " / 100" : texte + " " + u;
  }

  function ordinal(n) { return n === 1 ? "1er" : n + "e"; }

  function echapper(texte) {
    var div = document.createElement("div");
    div.textContent = texte == null ? "" : String(texte);
    return div.innerHTML;
  }

  function dateFr(iso, avecHeure) {
    if (!iso) return null;
    var d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
    if (isNaN(d)) return iso;
    var opts = { day: "numeric", month: "long", year: "numeric" };
    if (avecHeure) { opts.hour = "2-digit"; opts.minute = "2-digit"; }
    return d.toLocaleString("fr-FR", opts).replace(/^1 /, "1er ");
  }

  function proprietes() { return etat.geo.features.map(function (f) { return f.properties; }); }

  function nbDepartements() { return etat.geo.features.length; }

  // ---------------------------------------------------------------- régions

  function dansRegion(p) { return !etat.region || p.region === etat.region; }

  function regions() {
    var vues = {};
    proprietes().forEach(function (p) { if (p.region && p.region_nom) vues[p.region] = p.region_nom; });
    return Object.keys(vues).map(function (c) { return { code: c, nom: vues[c] }; })
      .sort(function (a, b) { return a.nom.localeCompare(b.nom, "fr"); });
  }

  function nomRegion(code) {
    var r = regions().find(function (x) { return x.code === code; });
    return r ? r.nom : "";
  }

  /* Rang d'un département parmi ceux de sa région (1 = meilleur, ex æquo = même rang). */
  function rangRegional(p, cle) {
    if (!p.region || p[cle] == null) return null;
    var voisins = proprietes().filter(function (q) { return q.region === p.region && q[cle] != null; });
    return { rang: 1 + voisins.filter(function (q) { return q[cle] > p[cle]; }).length, sur: voisins.length };
  }

  // ---------------------------------------------------------------- classes de couleur

  /* Seuils par quantiles : chaque couleur regroupe à peu près le même nombre de départements. */
  function calculerSeuils(cle) {
    var valeurs = proprietes().map(function (p) { return p[cle]; })
      .filter(function (v) { return v !== null && v !== undefined; })
      .sort(function (a, b) { return a - b; });
    if (!valeurs.length) return [];
    var seuils = [valeurs[0]];
    for (var i = 1; i < NB_CLASSES; i++) {
      seuils.push(valeurs[Math.floor(i * valeurs.length / NB_CLASSES)]);
    }
    seuils.push(valeurs[valeurs.length - 1]);
    return seuils;
  }

  function classe(valeur) {
    var s = etat.seuils;
    if (valeur === null || valeur === undefined || !s.length) return -1;
    for (var i = NB_CLASSES - 1; i >= 1; i--) {
      if (valeur >= s[i] && s[i] > s[0]) return i;
    }
    return 0;
  }

  function couleur(valeur) {
    var c = classe(valeur);
    return c < 0 ? COULEUR_INDISPO : COULEURS[c];
  }

  // ---------------------------------------------------------------- carte

  var carte = L.map("carte", { zoomSnap: 0.25, minZoom: 4, maxZoom: 18, attributionControl: true });
  carte.setView([46.6, 2.4], 5.75);

  // Fond OpenStreetMap, passé en gris (classe CSS « fond-gris ») pour laisser la couleur aux données.
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, className: "fond-gris",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">contributeurs OpenStreetMap</a>'
  }).addTo(carte);

  carte.createPane("calqueCyclOSM");
  carte.getPane("calqueCyclOSM").style.zIndex = 450;
  etat.calqueCyclOSM = L.tileLayer("https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm-lite/{z}/{x}/{y}.png", {
    subdomains: "abc", maxZoom: 18, pane: "calqueCyclOSM",
    attribution: 'Pistes : <a href="https://www.cyclosm.org">CyclOSM</a>'
  });

  /* Plus on zoome, plus les aplats s'effacent, pour laisser voir le plan et les pistes CyclOSM. */
  function opaciteAplat() {
    var z = carte.getZoom();
    return z <= 7 ? 0.82 : z <= 8 ? 0.6 : z <= 10 ? 0.35 : 0.15;
  }

  function styleDep(feature) {
    var p = feature.properties;
    var choisi = p.code === etat.selection;
    var opacite = opaciteAplat();
    if (!dansRegion(p)) {
      // Hors de la région filtrée : en retrait, mais toujours cliquable
      return { fillColor: couleur(p[etat.indicateur]), fillOpacity: opacite * 0.18,
               color: "#ffffff", weight: 0.5, opacity: 0.6 };
    }
    return {
      fillColor: couleur(p[etat.indicateur]),
      fillOpacity: p[etat.indicateur] == null ? opacite * 0.7 : opacite,
      color: choisi ? "#1f2a2e" : "#ffffff",
      weight: choisi ? 3 : 0.8,
      opacity: 1
    };
  }

  function texteInfobulle(p) {
    var v = avecUnite(p[etat.indicateur], etat.indicateur);
    return "<strong>" + echapper(p.nom) + "</strong>" + (v ? echapper(v) : "<em>Donnée indisponible</em>");
  }

  function dessinerDepartements() {
    etat.calqueDeps = L.geoJSON(etat.geo, {
      style: styleDep,
      onEachFeature: function (feature, couche) {
        etat.couches[feature.properties.code] = couche;
        couche.bindTooltip(function () { return texteInfobulle(feature.properties); },
          { sticky: true, className: "info-dep", direction: "top", offset: [0, -8] });
        couche.on({
          mouseover: function () { if (feature.properties.code !== etat.selection) couche.setStyle({ weight: 2, color: "#1f2a2e" }); },
          mouseout: function () { couche.setStyle(styleDep(feature)); },
          click: function () { choisirDepartement(feature.properties.code, false); }
        });
      }
    }).addTo(carte);
    carte.on("zoomend", recolorer);
    cadrerFrance();
    // Si la carte était invisible au chargement (onglet en arrière-plan, panneau replié),
    // sa taille était nulle : on recadre dès qu'elle prend une vraie taille.
    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        var t = carte.getSize();
        carte.invalidateSize();
        if (etat.cadrageAVide && t.x > 0 && t.y > 0) cadrerFrance();
      }).observe($("carte"));
    }
  }

  function cadrerFrance() {
    var t = carte.getSize();
    etat.cadrageAVide = !(t.x > 0 && t.y > 0);
    if (etat.cadrageAVide) return;
    carte.fitBounds(etat.calqueDeps.getBounds(), { padding: [10, 10], maxZoom: 7 });
  }

  function cadrerRegion() {
    var couches = proprietes().filter(dansRegion).map(function (p) { return etat.couches[p.code]; });
    if (!etat.region || !couches.length) { cadrerFrance(); return; }
    carte.flyToBounds(L.featureGroup(couches).getBounds(), { padding: [20, 20], maxZoom: 9, duration: 0.6 });
  }

  function recolorer() {
    etat.calqueDeps.setStyle(styleDep);
    if (etat.selection && etat.couches[etat.selection]) etat.couches[etat.selection].bringToFront();
  }

  // ---------------------------------------------------------------- légende

  function majLegende() {
    var ind = indicateur(etat.indicateur);
    $("legende-titre").textContent = ind.libelle + " (" + ind.unite + ")";
    var s = etat.seuils;
    var bande = $("legende-bande"), valeurs = $("legende-valeurs");
    bande.innerHTML = "";
    valeurs.innerHTML = "";
    if (!s.length) {
      valeurs.textContent = "Donnée indisponible pour tous les départements.";
    } else {
      COULEURS.forEach(function (c) {
        var seg = document.createElement("span");
        seg.style.background = c;
        bande.appendChild(seg);
      });
      // valeurs minimale, médiane et maximale sous la bande
      [s[0], s[Math.floor(s.length / 2)], s[s.length - 1]].forEach(function (v) {
        var e = document.createElement("span");
        e.textContent = formater(v, etat.indicateur);
        valeurs.appendChild(e);
      });
    }
    var manquants = proprietes().some(function (p) { return p[etat.indicateur] == null; });
    $("legende-indispo").hidden = !manquants;
  }

  // ---------------------------------------------------------------- classement

  function majClassement() {
    var cle = etat.indicateur, ind = indicateur(cle);
    var liste = proprietes().filter(function (p) { return p[cle] != null && dansRegion(p); })
      .sort(function (a, b) { return b[cle] - a[cle]; });
    // Une région compte au plus 13 départements : on les montre tous, sans onglets.
    var extrait = etat.region ? liste
      : etat.partie === "haut" ? liste.slice(0, 10) : liste.slice(-10).reverse();
    var max = liste.length ? liste[0][cle] : 0;
    $("classement-titre").textContent = (etat.region ? "Classement en " + nomRegion(etat.region) : "Classement") +
      " : " + ind.libelle.toLowerCase();
    document.querySelector(".onglets").hidden = !!etat.region;
    var rangDe = function (p) {
      return etat.region ? 1 + liste.filter(function (q) { return q[cle] > p[cle]; }).length : p.rangs[cle];
    };
    var ol = $("classement");
    ol.innerHTML = "";
    if (!extrait.length) {
      ol.innerHTML = '<li class="indispo">Donnée indisponible : le classement ne peut pas être établi.</li>';
      return;
    }
    extrait.forEach(function (p) {
      var li = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button";
      var largeur = max > 0 ? Math.max(2, p[cle] / max * 100) : 0;
      b.innerHTML = '<span class="rang">' + ordinal(rangDe(p)) + "</span>" +
        '<span class="nom">' + echapper(p.nom) + "</span>" +
        "<span>" + echapper(formater(p[cle], cle)) + "</span>" +
        '<span class="barre" aria-hidden="true" style="width:' + (largeur * 0.62).toFixed(1) + '%"></span>';
      b.setAttribute("aria-label", ordinal(rangDe(p)) + " : " + p.nom + ", " + avecUnite(p[cle], cle));
      b.addEventListener("click", function () { choisirDepartement(p.code, true); });
      li.appendChild(b);
      ol.appendChild(li);
    });
  }

  function choisirOnglet(partie) {
    etat.partie = partie;
    $("onglet-haut").setAttribute("aria-selected", partie === "haut");
    $("onglet-bas").setAttribute("aria-selected", partie === "bas");
    majClassement();
  }

  // ---------------------------------------------------------------- fiche département

  function ligneFiche(p, cle) {
    var ind = indicateur(cle);
    var v = avecUnite(p[cle], cle);
    var rang = p.rangs && p.rangs[cle];
    var rr = etat.region ? rangRegional(p, cle) : null;
    var texteRang = rang ? ordinal(rang) + " sur " + nbDepartements() : "";
    if (rr) texteRang += (texteRang ? ", " : "") + ordinal(rr.rang) + " sur " + rr.sur + " dans la région";
    var cellule = v
      ? echapper(v) + (texteRang ? '<span class="rang">' + texteRang + "</span>" : "")
      : '<span class="indispo">indisponible</span>';
    return '<tr class="' + (cle === etat.indicateur ? "actif" : "") + '"><th scope="row">' +
      echapper(ind.libelle) + "</th><td>" + cellule + "</td></tr>";
  }

  function majFiche() {
    var fiche = $("fiche");
    if (!etat.selection || etat.ville) { fiche.hidden = true; return; }
    var p = proprietes().find(function (q) { return q.code === etat.selection; });
    if (!p) { fiche.hidden = true; return; }

    var groupes = {};
    etat.meta.indicateurs.forEach(function (i) {
      if (i.cle === "score") return;
      (groupes[i.groupe] = groupes[i.groupe] || []).push(i.cle);
    });
    var lignes = "";
    lignes += '<tr class="groupe"><th scope="rowgroup" colspan="2">Population et surface</th></tr>';
    if (p.region_nom) lignes += '<tr><th scope="row">Région</th><td>' + echapper(p.region_nom) + "</td></tr>";
    lignes += '<tr><th scope="row">Population</th><td>' + (p.population != null
      ? echapper(new Intl.NumberFormat("fr-FR").format(p.population)) + " hab." : '<span class="indispo">indisponible</span>') + "</td></tr>";
    lignes += '<tr><th scope="row">Surface</th><td>' + (p.surface_km2 != null
      ? echapper(new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(p.surface_km2)) + " km²" : '<span class="indispo">indisponible</span>') + "</td></tr>";
    Object.keys(groupes).forEach(function (g) {
      lignes += '<tr class="groupe"><th scope="rowgroup" colspan="2">' + echapper(g) + "</th></tr>";
      groupes[g].forEach(function (cle) { lignes += ligneFiche(p, cle); });
    });

    var score = p.score != null
      ? '<div class="score-bloc"><span class="valeur">' + formater(p.score, "score") + '</span><span class="unite">/ 100, ' +
        ordinal(p.rangs.score) + " sur " + nbDepartements() + "</span></div>" +
        (function () {
          var rr = rangRegional(p, "score");
          return rr ? '<p class="rang-region">' + ordinal(rr.rang) + " sur " + rr.sur + " en " +
            echapper(p.region_nom) + "</p>" : "";
        })()
      : '<div class="score-bloc"><span class="indispo">Score indisponible</span></div>';
    var partiel = p.score != null && p.score_nb_indicateurs < etat.meta.score_indicateurs.length
      ? '<p class="indispo">Score calculé sur ' + p.score_nb_indicateurs + " indicateurs sur " +
        etat.meta.score_indicateurs.length + " (données manquantes).</p>" : "";

    fiche.innerHTML =
      '<div class="fiche-tete"><h2>' + echapper(p.nom) + ' <span class="code">(' + echapper(p.code) + ")</span></h2>" +
      '<button type="button" class="bouton-fermer" id="fermer-fiche" aria-label="Fermer la fiche">×</button></div>' +
      score + partiel + "<table>" + lignes + "</table>";
    fiche.hidden = false;
    $("fermer-fiche").addEventListener("click", function () { choisirDepartement(null, false); });
  }

  function choisirDepartement(code, recentrer) {
    if (etat.ville && RechercheVille.departement(etat.ville) !== code) choisirVille(null);
    etat.selection = code || null;
    var p = etat.selection && proprietes().find(function (q) { return q.code === etat.selection; });
    if (p && !dansRegion(p)) choisirRegion(null, false);
    $("choix-dep").value = etat.selection || "";
    recolorer();
    majFiche();
    majAdresse();
    if (etat.selection && recentrer && etat.couches[etat.selection]) {
      carte.flyToBounds(etat.couches[etat.selection].getBounds(), { padding: [30, 30], maxZoom: 9, duration: 0.6 });
    }
    if (etat.selection && window.matchMedia("(max-width: 820px)").matches) {
      $("fiche").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  // ---------------------------------------------------------------- indicateur

  function choisirIndicateur(cle) {
    if (!indicateur(cle)) cle = "score";
    etat.indicateur = cle;
    $("choix-indicateur").value = cle;
    etat.seuils = calculerSeuils(cle);
    recolorer();
    majLegende();
    majClassement();
    majFiche();
    majResumeRegion();
    majAdresse();
  }

  // ---------------------------------------------------------------- filtre régional

  /* Totaux de la région : sommes des départements. Si un seul département manque
     la donnée, le total est indisponible (on n'additionne pas des trous). */
  function totalRegion(cle) {
    var deps = proprietes().filter(dansRegion);
    if (!deps.length || deps.some(function (p) { return p[cle] == null; })) return null;
    return deps.reduce(function (s, p) { return s + p[cle]; }, 0);
  }

  function majResumeRegion() {
    var bloc = $("resume-region");
    if (!etat.region) { bloc.hidden = true; return; }
    var nb = proprietes().filter(dansRegion).length;
    var km = totalRegion("km_total"), pop = totalRegion("population"), surf = totalRegion("surface_km2");
    var st = totalRegion("vls_stations"), velos = totalRegion("vls_velos");
    var f0 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
    var f1 = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    var f2 = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    var ligne = function (libelle, valeur) {
      return '<tr><th scope="row">' + libelle + "</th><td>" +
        (valeur == null ? '<span class="indispo">indisponible</span>' : echapper(valeur)) + "</td></tr>";
    };
    bloc.innerHTML =
      '<div class="fiche-tete"><h2>' + echapper(nomRegion(etat.region)) + "</h2>" +
      '<button type="button" class="bouton-fermer" id="fermer-region" aria-label="Revenir à toute la France">×</button></div>' +
      '<p class="sous-titre">' + nb + " départements. Totaux de la région :</p><table>" +
      ligne("Aménagements cyclables", km == null ? null : f0.format(km) + " km") +
      ligne("Pour 10 000 habitants", km == null || !pop ? null : f1.format(km / pop * 1e4) + " km") +
      ligne("Densité", km == null || !surf ? null : f2.format(km / surf) + " km / km²") +
      ligne("Stations de vélos en libre-service", st == null ? null : f0.format(st)) +
      ligne("Pour 100 000 habitants", st == null || !pop ? null : f1.format(st / pop * 1e5)) +
      ligne("Vélos disponibles", velos == null ? null : f0.format(velos)) +
      ligne("Population", pop == null ? null : f0.format(pop) + " hab.") +
      "</table>";
    bloc.hidden = false;
    $("fermer-region").addEventListener("click", function () { choisirRegion(null, true); });
  }

  function remplirDepartements() {
    var sel = $("choix-dep");
    sel.innerHTML = '<option value="">Choisir…</option>';
    proprietes().filter(dansRegion).slice()
      .sort(function (a, b) { return a.nom.localeCompare(b.nom, "fr"); })
      .forEach(function (p) {
        var o = document.createElement("option");
        o.value = p.code;
        o.textContent = p.nom + " (" + p.code + ")";
        sel.appendChild(o);
      });
    sel.value = etat.selection || "";
  }

  function choisirRegion(code, recadrer) {
    etat.region = code && nomRegion(code) ? code : null;
    $("choix-region").value = etat.region || "";
    var p = etat.selection && proprietes().find(function (q) { return q.code === etat.selection; });
    if (p && !dansRegion(p)) { etat.selection = null; majFiche(); }
    remplirDepartements();
    recolorer();
    majClassement();
    majFiche();
    majResumeRegion();
    majAdresse();
    if (recadrer) cadrerRegion();
  }

  // ---------------------------------------------------------------- adresse partageable (#ind=…&dep=…)

  function lireAdresse() {
    var params = new URLSearchParams(location.hash.slice(1));
    var requete = new URLSearchParams(location.search);
    return { ind: params.get("ind"), dep: params.get("dep"), reg: params.get("reg"),
             ville: requete.get("ville"), arr: requete.get("arr") };
  }

  /* La ville est dans la requête (?ville=CODE_INSEE, comme sur la page Statistiques),
     le reste de l'état de la carte dans l'ancre (#ind=…&reg=…&dep=…). */
  function majAdresse() {
    var params = new URLSearchParams();
    if (etat.indicateur !== "score") params.set("ind", etat.indicateur);
    if (etat.region) params.set("reg", etat.region);
    if (etat.selection) params.set("dep", etat.selection);
    var requete = new URLSearchParams();
    if (etat.ville) requete.set("ville", etat.ville);
    if (etat.ville && etat.arr) requete.set("arr", etat.arr);
    var q = requete.toString(), h = params.toString();
    history.replaceState(null, "", location.pathname + (q ? "?" + q : "") + (h ? "#" + h : ""));
    var lien = $("lien-stats");
    if (lien) {
      var st = new URLSearchParams();
      if (etat.ville) { st.set("ville", etat.ville); if (etat.arr) st.set("arr", etat.arr); }
      else if (etat.selection) st.set("dep", etat.selection);
      else if (etat.region) st.set("region", etat.region);
      lien.href = "statistiques.html" + (st.toString() ? "?" + st.toString() : "");
    }
  }

  // ---------------------------------------------------------------- ville

  var fichiersDep = {};
  function fichierDep(chemin) {
    if (!fichiersDep[chemin]) {
      fichiersDep[chemin] = fetch("data/" + chemin).then(function (r) { if (!r.ok) throw new Error(chemin); return r.json(); });
      fichiersDep[chemin].catch(function () { delete fichiersDep[chemin]; });
    }
    return fichiersDep[chemin];
  }

  var SEUIL_RANG = 2000; // habitants : en dessous, les rangs par habitant n'ont pas de sens

  function choisirVille(code, arr, recentrer) {
    if (etat.calqueVille) { carte.removeLayer(etat.calqueVille); etat.calqueVille = null; }
    etat.ville = code || null;
    etat.arr = code ? (arr || null) : null;
    if (!etat.ville) {
      $("fiche-ville").hidden = true;
      rechercheVille.afficher("");
      majFiche();
      majAdresse();
      return;
    }
    var dep = RechercheVille.departement(etat.ville);
    // La ville doit rester compatible avec le filtre régional
    var pDep = proprietes().find(function (q) { return q.code === dep; });
    if (pDep && !dansRegion(pDep)) choisirRegion(null, false);
    etat.selection = pDep ? dep : null;
    $("choix-dep").value = etat.selection || "";
    recolorer();
    majFiche();
    majAdresse();
    var fiche = $("fiche-ville");
    fiche.hidden = false;
    fiche.innerHTML = '<p class="indispo">Chargement de la fiche…</p>';
    Promise.all([fichierDep("communes/" + dep + ".json"),
                 fichierDep("contours/" + dep + ".geojson").catch(function () { return null; })])
      .then(function (res) {
        if (etat.ville !== code) return;          // une autre ville a été choisie entre-temps
        var f = res[0], contours = res[1];
        var c = f.communes[code];
        if (!c) throw new Error("commune absente");
        rechercheVille.afficher(c.n || code);
        var forme = contours && contours.features.find(function (x) { return x.properties.code === code; });
        if (forme) {
          etat.calqueVille = L.geoJSON(forme, { interactive: false,
            style: { color: "#1f2a2e", weight: 3, fill: true, fillColor: "#ffffff", fillOpacity: 0.12 } }).addTo(carte);
          if (recentrer !== false) carte.flyToBounds(etat.calqueVille.getBounds(), { padding: [30, 30], maxZoom: 13, duration: 0.6 });
        }
        dessinerFicheVille(f, code, forme);
        if (window.matchMedia("(max-width: 820px)").matches) fiche.scrollIntoView({ behavior: "smooth", block: "start" });
      }).catch(function () {
        fiche.innerHTML = '<p class="message-erreur" role="alert">La fiche de cette ville n\'a pas pu être chargée. Réessayez dans quelques minutes.</p>';
      });
  }

  /* Rang de la ville parmi les communes du département de plus de SEUIL_RANG habitants. */
  function rangDansDep(f, code, valeur) {
    var c = f.communes[code];
    if (!c || !c.p || c.p < SEUIL_RANG) return null;
    var v = valeur(c);
    if (v == null) return null;
    var autres = Object.keys(f.communes).map(function (k) { return f.communes[k]; })
      .filter(function (x) { return x.p >= SEUIL_RANG; }).map(valeur).filter(function (x) { return x != null; });
    return { rang: 1 + autres.filter(function (x) { return x > v; }).length, sur: autres.length };
  }

  function accidentsVille(f, code) {
    var champs = f.accidents.champs, k = {};
    champs.forEach(function (ch, i) { k[ch] = i; });
    var par = {};
    f.accidents.lignes.forEach(function (l) {
      if (l[k.com] !== code) return;
      var a = par[l[k.an]] = par[l[k.an]] || { acc: 0, tues: 0, blesses: 0 };
      a.acc++; a.tues += l[k.tues]; a.blesses += l[k.hosp] + l[k.legers];
    });
    return par;
  }

  function dessinerFicheVille(f, code, forme) {
    var c = f.communes[code], fmt0 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
    var fmt1 = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    var fmt2 = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    var indispo = '<span class="indispo">indisponible</span>';
    var dep = proprietes().find(function (q) { return q.code === f.dep; }) || {};
    var km = c.km ? c.km.t : null, pop = c.p;
    var ligne = function (lib, val, rang) {
      return '<tr><th scope="row">' + lib + "</th><td>" + (val == null ? indispo : echapper(val)) +
        (rang ? '<span class="rang">' + ordinal(rang.rang) + " sur " + rang.sur + " dans le département</span>" : "") + "</td></tr>";
    };
    var html = '<div class="fiche-tete"><h2>' + echapper(c.n || code) + ' <span class="code">(' + code + ")</span></h2>" +
      '<button type="button" class="bouton-fermer" id="fermer-ville" aria-label="Fermer la fiche de la ville">×</button></div>' +
      '<p class="sous-titre-ville">' + echapper(dep.nom || f.dep) + (dep.region_nom ? ", " + echapper(dep.region_nom) : "") + "</p>";
    if (etat.arr) {
      html += '<p class="note-ville">Chiffres pour toute la commune. Le détail des accidents par arrondissement est sur la page Statistiques.</p>';
    }
    if (!forme) html += '<p class="note-ville">Contour de la commune indisponible.</p>';
    html += "<table>";
    html += '<tr class="groupe"><th scope="rowgroup" colspan="2">Population et surface</th></tr>';
    html += ligne("Population", pop != null ? fmt0.format(pop) + " hab." : null);
    html += ligne("Surface", c.s != null ? fmt1.format(c.s) + " km²" : null);
    html += '<tr class="groupe"><th scope="rowgroup" colspan="2">Aménagements cyclables</th></tr>';
    html += ligne("Total", km != null ? fmt1.format(km) + " km" : null,
                  rangDansDep(f, code, function (x) { return x.km ? x.km.t : null; }));
    html += ligne("Pour 10 000 habitants", km != null && pop ? fmt1.format(km / pop * 1e4) + " km" : null,
                  rangDansDep(f, code, function (x) { return x.km && x.p ? x.km.t / x.p * 1e4 : null; }));
    if (c.km) {
      [["pistes", "Pistes cyclables"], ["bandes", "Bandes cyclables"], ["voies_vertes", "Voies vertes"],
       ["double_sens", "Double-sens cyclables"], ["autres", "Autres aménagements"]].forEach(function (t) {
        if (c.km[t[0]]) html += ligne(t[1], fmt1.format(c.km[t[0]]) + " km");
      });
    }
    html += '<tr class="groupe"><th scope="rowgroup" colspan="2">Vélos en libre-service</th></tr>';
    if (c.vls) {
      html += ligne("Stations", fmt0.format(c.vls.st));
      if (c.vls.zv) html += ligne("Zones de stationnement en free-floating", fmt0.format(c.vls.zv));
      html += ligne("Vélos disponibles (relevé du jour)", fmt0.format(c.vls.v));
    } else {
      html += ligne("Stations", null);
    }
    html += "</table>";

    // Accidents : sélecteur d'année, mini-graphique, ratios de l'année choisie
    var par = accidentsVille(f, code);
    var annees = Object.keys(par).map(Number);
    var srcAcc = etat.meta.sources.accidents || {};
    html += '<h3 class="titre-section-ville">Accidents de vélo</h3>';
    if (!srcAcc.statut || srcAcc.statut === "indisponible" || !srcAcc.annees) {
      html += '<p class="indispo">Données d\'accidents indisponibles.</p>';
    } else {
      var premiere = srcAcc.annees[0], derniere = srcAcc.annees[1];
      var liste = [];
      for (var a = premiere; a <= derniere; a++) liste.push(a);
      if (!etat.anneeVille || liste.indexOf(etat.anneeVille) < 0) etat.anneeVille = derniere;
      html += '<div class="champ-annee"><label for="annee-ville">Année</label> <select id="annee-ville">' +
        liste.slice().reverse().map(function (a) { return '<option value="' + a + '">' + a + "</option>"; }).join("") + "</select></div>";
      html += '<div id="acc-annee"></div>';
      html += '<figure class="mini-graphe"><figcaption>Accidents par année, ' + premiere + "–" + derniere + "</figcaption>" +
        miniGraphe(liste, par) + "</figure>";
      html += '<details><summary>Voir les données</summary><table class="donnees-ville"><thead><tr><th scope="col">Année</th><th scope="col">Accidents</th><th scope="col">Tués</th><th scope="col">Blessés</th></tr></thead><tbody>' +
        liste.map(function (a) { var v = par[a] || { acc: 0, tues: 0, blesses: 0 };
          return '<tr><th scope="row">' + a + "</th><td>" + v.acc + "</td><td>" + v.tues + "</td><td>" + v.blesses + "</td></tr>"; }).join("") +
        "</tbody></table></details>";
      html += '<p class="note-ville">À partir de 2018, la source sous-estime les accidents (vélos électriques probablement absents).</p>';
    }
    var st = new URLSearchParams({ ville: code });
    if (etat.arr) st.set("arr", etat.arr);
    html += '<p><a class="lien-stats-ville" href="statistiques.html?' + st.toString() + '">Voir toutes les statistiques de cette ville</a></p>';
    $("fiche-ville").innerHTML = html;
    $("fermer-ville").addEventListener("click", function () { choisirVille(null); });
    var sel = $("annee-ville");
    if (sel) {
      sel.value = etat.anneeVille;
      var majAnnee = function () {
        var an = etat.anneeVille, v = par[an] || { acc: 0, tues: 0, blesses: 0 };
        $("acc-annee").innerHTML = "<table>" +
          ligne("Accidents en " + an, fmt0.format(v.acc)) +
          ligne("Cyclistes tués", fmt0.format(v.tues)) +
          ligne("Cyclistes blessés", fmt0.format(v.blesses)) +
          ligne("Pour 100 000 habitants", pop ? fmt1.format(v.acc / pop * 1e5) + (v.acc < 10 ? "*" : "") : null) +
          ligne("Pour 100 km d'aménagements", km ? fmt2.format(v.acc / km * 100) + (v.acc < 10 ? "*" : "") : null) +
          "</table>" + (v.acc < 10 ? '<p class="note-ville">* Moins de 10 accidents cette année-là : ratio peu significatif.</p>' : "");
        $("fiche-ville").querySelectorAll(".mini-graphe rect[data-an]").forEach(function (r) {
          r.setAttribute("class", Number(r.getAttribute("data-an")) === an ? "barre-active" : "");
        });
      };
      sel.addEventListener("change", function () { etat.anneeVille = Number(sel.value); majAnnee(); });
      majAnnee();
    }
  }

  /* Petit histogramme SVG (pas de bibliothèque sur la page carte) */
  function miniGraphe(annees, par) {
    var max = Math.max.apply(null, annees.map(function (a) { return (par[a] || {}).acc || 0; }).concat([1]));
    var l = 300, h = 80, pas = l / annees.length;
    var barres = annees.map(function (a, i) {
      var v = (par[a] || {}).acc || 0, bh = Math.max(v ? 2 : 0, v / max * (h - 14));
      return '<rect data-an="' + a + '" x="' + (i * pas + 1).toFixed(1) + '" y="' + (h - bh).toFixed(1) +
        '" width="' + Math.max(1, pas - 2).toFixed(1) + '" height="' + bh.toFixed(1) + '"><title>' + a + " : " + v + " accident" + (v > 1 ? "s" : "") + "</title></rect>";
    }).join("");
    return '<svg viewBox="0 0 ' + l + " " + (h + 14) + '" role="img" aria-label="Histogramme des accidents par année ; valeurs dans le tableau ci-dessous">' +
      barres + '<text x="0" y="' + (h + 12) + '">' + annees[0] + '</text><text x="' + l + '" y="' + (h + 12) +
      '" text-anchor="end">' + annees[annees.length - 1] + '</text><text x="0" y="10">max ' + max + "</text></svg>";
  }

  var rechercheVille = null;

  // ---------------------------------------------------------------- calque VLS

  function activerVLS(actif) {
    if (!actif) { if (etat.calqueVLS) carte.removeLayer(etat.calqueVLS); return; }
    if (etat.calqueVLS) { carte.addLayer(etat.calqueVLS); return; }
    $("vls-info").textContent = "Chargement des stations…";
    fetch("data/stations.json").then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (donnees) {
      var groupe = L.markerClusterGroup({
        chunkedLoading: true, showCoverageOnHover: false, maxClusterRadius: 50,
        iconCreateFunction: function (c) {
          var n = c.getChildCount();
          var taille = n < 100 ? 34 : n < 1000 ? 42 : 50;
          return L.divIcon({ html: "<span>" + n + "</span>", className: "cluster-vls",
            iconSize: [taille, taille] });
        }
      });
      var marqueurs = donnees.stations.map(function (s) {
        var m = L.circleMarker([s[0], s[1]], { radius: 6, color: "#ffffff", weight: 1.5,
          fillColor: "#0e7c5a", fillOpacity: 1 });
        var velos = s[3] == null ? "disponibilité inconnue"
          : s[3] + (s[3] > 1 ? " vélos disponibles" : " vélo disponible");
        if (s[5] === 1) m.setStyle({ fillColor: "#ffffff", color: "#0e7c5a", weight: 2 });
        m.bindPopup("<strong>" + echapper(s[2] || "Station") + "</strong><br>" +
          (s[5] === 1 ? "Zone de stationnement d'un service en free-floating<br>" : "") + echapper(velos) +
          "<br><small>" + echapper(donnees.systemes[s[4]] || "") + "</small>");
        return m;
      });
      groupe.addLayers(marqueurs);
      etat.calqueVLS = groupe;
      if ($("calque-vls").checked) carte.addLayer(groupe);
      $("vls-info").textContent = new Intl.NumberFormat("fr-FR").format(marqueurs.length) +
        " stations, regroupées par secteur ; zoomez pour les détailler.";
    }).catch(function () {
      $("vls-info").textContent = "Stations indisponibles pour le moment.";
      $("calque-vls").checked = false;
    });
  }

  // ---------------------------------------------------------------- démarrage

  function remplirSelecteurs() {
    var sel = $("choix-indicateur");
    var groupes = {};
    etat.meta.indicateurs.forEach(function (i) {
      if (!groupes[i.groupe]) {
        groupes[i.groupe] = document.createElement("optgroup");
        groupes[i.groupe].label = i.groupe;
        sel.appendChild(groupes[i.groupe]);
      }
      var o = document.createElement("option");
      o.value = i.cle;
      o.textContent = i.libelle;
      groupes[i.groupe].appendChild(o);
    });

    remplirDepartements();

    // Filtre régional : masqué si la source des régions est indisponible
    var liste = regions();
    $("champ-region").hidden = !liste.length;
    liste.forEach(function (r) {
      var o = document.createElement("option");
      o.value = r.code;
      o.textContent = r.nom;
      $("choix-region").appendChild(o);
    });
  }

  function afficherMaj() {
    var m = etat.meta, a = (m.sources || {}).amenagements || {};
    var texte = "Mise à jour des données : " + (dateFr(m.genere_le, true) || "inconnue");
    if (a.date_donnees) texte += ". Aménagements cyclables à jour au " + dateFr(a.date_donnees) + ".";
    var alertes = Object.keys(m.sources || {}).filter(function (k) { return m.sources[k].statut !== "ok"; });
    if (alertes.length) texte += " Certaines sources n'ont pas pu être actualisées : voir Sources et méthode.";
    $("maj").textContent = texte;
  }

  function erreur(message) {
    $("legende-titre").innerHTML = '<span class="message-erreur" role="alert">' + echapper(message) + "</span>";
  }

  Promise.all([
    fetch("data/meta.json").then(function (r) { if (!r.ok) throw new Error("meta"); return r.json(); }),
    fetch("data/departements.geojson").then(function (r) { if (!r.ok) throw new Error("geo"); return r.json(); })
  ]).then(function (res) {
    etat.meta = res[0];
    etat.geo = res[1];
    remplirSelecteurs();
    dessinerDepartements();
    afficherMaj();

    rechercheVille = RechercheVille.attacher($("recherche-ville"), $("suggestions-ville"), function (v) {
      etat.anneeVille = null;
      choisirVille(v.entiere || v.code, v.entiere ? v.code : null, true);
    });

    var adresse = lireAdresse();
    choisirIndicateur(adresse.ind || "score");
    if (adresse.reg) choisirRegion(adresse.reg, !adresse.dep && !adresse.ville);
    if (adresse.ville && /^[0-9AB]{5}$/i.test(adresse.ville)) choisirVille(adresse.ville.toUpperCase(), adresse.arr, true);
    else if (adresse.dep && etat.couches[adresse.dep]) choisirDepartement(adresse.dep, true);

    $("choix-indicateur").addEventListener("change", function (e) { choisirIndicateur(e.target.value); });
    $("choix-dep").addEventListener("change", function (e) { choisirDepartement(e.target.value, true); });
    $("choix-region").addEventListener("change", function (e) { choisirRegion(e.target.value, true); });
    $("onglet-haut").addEventListener("click", function () { choisirOnglet("haut"); });
    $("onglet-bas").addEventListener("click", function () { choisirOnglet("bas"); });
    $("calque-vls").addEventListener("change", function (e) { activerVLS(e.target.checked); });
    $("calque-cyclosm").addEventListener("change", function (e) {
      if (e.target.checked) etat.calqueCyclOSM.addTo(carte); else carte.removeLayer(etat.calqueCyclOSM);
    });
  }).catch(function (e) {
    if (window.console) console.error(e);
    erreur("Les données n'ont pas pu être chargées. Elles sont générées automatiquement chaque jour : réessayez dans quelques minutes.");
  });
})();
