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
    var liste = proprietes().filter(function (p) { return p[cle] != null; })
      .sort(function (a, b) { return b[cle] - a[cle]; });
    var extrait = etat.partie === "haut" ? liste.slice(0, 10) : liste.slice(-10).reverse();
    var max = liste.length ? liste[0][cle] : 0;
    $("classement-titre").textContent = "Classement : " + ind.libelle.toLowerCase();
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
      b.innerHTML = '<span class="rang">' + ordinal(p.rangs[cle]) + "</span>" +
        '<span class="nom">' + echapper(p.nom) + "</span>" +
        "<span>" + echapper(formater(p[cle], cle)) + "</span>" +
        '<span class="barre" aria-hidden="true" style="width:' + (largeur * 0.62).toFixed(1) + '%"></span>';
      b.setAttribute("aria-label", ordinal(p.rangs[cle]) + " : " + p.nom + ", " + avecUnite(p[cle], cle));
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
    var cellule = v
      ? echapper(v) + (rang ? '<span class="rang">' + ordinal(rang) + " sur " + nbDepartements() + "</span>" : "")
      : '<span class="indispo">indisponible</span>';
    return '<tr class="' + (cle === etat.indicateur ? "actif" : "") + '"><th scope="row">' +
      echapper(ind.libelle) + "</th><td>" + cellule + "</td></tr>";
  }

  function majFiche() {
    var fiche = $("fiche");
    if (!etat.selection) { fiche.hidden = true; return; }
    var p = proprietes().find(function (q) { return q.code === etat.selection; });
    if (!p) { fiche.hidden = true; return; }

    var groupes = {};
    etat.meta.indicateurs.forEach(function (i) {
      if (i.cle === "score") return;
      (groupes[i.groupe] = groupes[i.groupe] || []).push(i.cle);
    });
    var lignes = "";
    lignes += '<tr class="groupe"><th scope="rowgroup" colspan="2">Population et surface</th></tr>';
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
        ordinal(p.rangs.score) + " sur " + nbDepartements() + "</span></div>"
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
    etat.selection = code || null;
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
    majAdresse();
  }

  // ---------------------------------------------------------------- adresse partageable (#ind=…&dep=…)

  function lireAdresse() {
    var params = new URLSearchParams(location.hash.slice(1));
    return { ind: params.get("ind"), dep: params.get("dep") };
  }

  function majAdresse() {
    var params = new URLSearchParams();
    if (etat.indicateur !== "score") params.set("ind", etat.indicateur);
    if (etat.selection) params.set("dep", etat.selection);
    var h = params.toString();
    history.replaceState(null, "", h ? "#" + h : location.pathname + location.search);
  }

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
        m.bindPopup("<strong>" + echapper(s[2] || "Station") + "</strong><br>" + echapper(velos) +
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

    var deps = proprietes().slice().sort(function (a, b) { return a.nom.localeCompare(b.nom, "fr"); });
    deps.forEach(function (p) {
      var o = document.createElement("option");
      o.value = p.code;
      o.textContent = p.nom + " (" + p.code + ")";
      $("choix-dep").appendChild(o);
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

    var adresse = lireAdresse();
    choisirIndicateur(adresse.ind || "score");
    if (adresse.dep && etat.couches[adresse.dep]) choisirDepartement(adresse.dep, true);

    $("choix-indicateur").addEventListener("change", function (e) { choisirIndicateur(e.target.value); });
    $("choix-dep").addEventListener("change", function (e) { choisirDepartement(e.target.value, true); });
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
