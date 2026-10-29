/* Carte Vélo France — code commun aux deux cartes (carte d'accueil et carte détaillée).
   Expose window.CVF :
     - formats (echapper, ordinal, dateFr, nombre) et palette de couleurs ;
     - fichier(chemin) : lecture des fichiers de données, mise en cache ;
     - creerCarte(id) : carte Leaflet avec le fond OpenStreetMap en gris ;
     - creerCalques(carte, options) : les quatre calques (vélos en libre-service, pistes CyclOSM,
       stationnement, lieux à visiter) et leurs bascules flottantes, toujours visibles.
   Nécessite Leaflet et Leaflet.markercluster. */
(function () {
  "use strict";

  // ---------------------------------------------------------------- formats et couleurs

  // Palette séquentielle (5 classes) : du vert très clair au vert foncé.
  var COULEURS = ["#e3f2ea", "#a8d8bf", "#5fb592", "#21885f", "#0b5a40"];
  var COULEUR_INDISPO = "#c9cfcc";

  function echapper(texte) {
    var div = document.createElement("div");
    div.textContent = texte == null ? "" : String(texte);
    return div.innerHTML;
  }

  function ordinal(n) { return n === 1 ? "1er" : n + "e"; }

  function nombre(v, decimales) {
    var d = decimales || 0;
    return new Intl.NumberFormat("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
  }

  function dateFr(iso, avecHeure) {
    if (!iso) return null;
    var d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
    if (isNaN(d)) return iso;
    var opts = { day: "numeric", month: "long", year: "numeric" };
    if (avecHeure) { opts.hour = "2-digit"; opts.minute = "2-digit"; }
    return d.toLocaleString("fr-FR", opts).replace(/^1 /, "1er ");
  }

  /* Seuils par quantiles : chaque couleur regroupe à peu près le même nombre de territoires. */
  function seuilsQuantiles(valeurs) {
    var v = valeurs.filter(function (x) { return x !== null && x !== undefined; }).sort(function (a, b) { return a - b; });
    if (!v.length) return [];
    var s = [v[0]];
    for (var i = 1; i < COULEURS.length; i++) s.push(v[Math.floor(i * v.length / COULEURS.length)]);
    s.push(v[v.length - 1]);
    return s;
  }

  function classe(valeur, seuils) {
    if (valeur === null || valeur === undefined || !seuils.length) return -1;
    for (var i = COULEURS.length - 1; i >= 1; i--) {
      if (valeur >= seuils[i] && seuils[i] > seuils[0]) return i;
    }
    return 0;
  }

  function couleur(valeur, seuils) {
    var c = classe(valeur, seuils);
    return c < 0 ? COULEUR_INDISPO : COULEURS[c];
  }

  // ---------------------------------------------------------------- données

  var cache = {};
  function fichier(chemin) {
    if (!cache[chemin]) {
      cache[chemin] = fetch("data/" + chemin).then(function (r) { if (!r.ok) throw new Error(chemin); return r.json(); });
      cache[chemin].catch(function () { delete cache[chemin]; });
    }
    return cache[chemin];
  }

  // ---------------------------------------------------------------- carte

  function creerCarte(id) {
    var carte = L.map(id, { zoomSnap: 0.25, minZoom: 4, maxZoom: 18, attributionControl: true });
    carte.setView([46.6, 2.4], 5.75);
    // Fond OpenStreetMap, passé en gris (classe CSS « fond-gris ») pour laisser la couleur aux données.
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, className: "fond-gris",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">contributeurs OpenStreetMap</a>'
    }).addTo(carte);
    return carte;
  }

  // ---------------------------------------------------------------- calques

  var ZOOM_DETAIL = 11;   // stationnement et lieux : chargés seulement en zoomant sur une ville

  // Lieux à visiter : couleurs catégorielles validées (outil dataviz) ; le pictogramme porte aussi la catégorie.
  var POI_COULEURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"];
  var POI_PICTOS = [
    '<path d="M3 13h10M4 6h8M5 6v6M8 6v6M11 6v6M3 6l5-3 5 3" />',                 // musée : colonnes
    '<path d="M3 13V6l2-1v2l2-1v2l2-1V6l2-1v8M3 13h10" />',                        // monument : créneaux
    '<path d="M8 2v3M6.5 3.5h3M4 13V8l4-3 4 3v5M7 13v-3h2v3" />',                    // patrimoine : chapelle
    '<path d="M8 13v-3M8 10c-3 0-4-2-4-4 0-2 2-4 4-4s4 2 4 4c0 2-1 4-4 4z" />',     // parc : arbre
    '<path d="M2 13l4-7 3 4 2-3 3 6z" />',                                         // nature : montagne
    '<circle cx="4.5" cy="10.5" r="2.5"/><circle cx="11.5" cy="10.5" r="2.5"/><path d="M4.5 10.5L7 6h3l1.5 4.5M7 6l1 4.5" />', // vélo
    '<path d="M10 3a3 3 0 0 0-3 4L3 11l2 2 4-4a3 3 0 0 0 4-3l-2 1-1-1 1-2z" />'      // clé
  ];
  var POI_NOMS_COURTS = ["Musée", "Monument historique", "Patrimoine", "Parc ou jardin", "Nature", "Itinéraire vélo", "Location, réparation"];

  // Bascules : ordre, libellé court, infobulle, pictogramme
  var BASCULES = [
    { nom: "vls", libelle: "Libre-service", aide: "Stations de vélos en libre-service",
      picto: '<circle cx="5" cy="15" r="3.2"/><circle cx="15" cy="15" r="3.2"/><path d="M5 15l3-6h5l2 6M8 9l2 6M12 6h2"/>' },
    { nom: "cyclosm", libelle: "Pistes", aide: "Pistes et bandes cyclables (CyclOSM)",
      picto: '<path d="M6 18L9 2M14 18L11 2M10 4v2M10 9v2M10 14v2"/>' },
    { nom: "stationnement", libelle: "Stationnement", aide: "Stationnement vélo (OpenStreetMap)",
      picto: '<rect x="3" y="3" width="14" height="14" rx="3"/><path d="M8 14V6h3a2.5 2.5 0 0 1 0 5H8"/>' },
    { nom: "poi", libelle: "À visiter", aide: "Lieux à visiter à vélo",
      picto: '<path d="M10 18s-5.5-5.2-5.5-9A5.5 5.5 0 0 1 15.5 9c0 3.8-5.5 9-5.5 9z"/><circle cx="10" cy="9" r="2"/>' }
  ];

  /* options :
       departementsVisibles() -> codes des départements à charger (stationnement, lieux)
       villeActive()          -> vrai si une ville est choisie (les lieux se chargent alors sans zoomer)
       legendes               -> élément où afficher la légende des calques actifs (facultatif) */
  function creerCalques(carte, options) {
    options = options || {};
    var actifs = {}, boutons = {}, couches = {}, statCharges = {}, poiCharges = {};
    var statut = null;

    carte.createPane("calqueCyclOSM");
    carte.getPane("calqueCyclOSM").style.zIndex = 450;
    couches.cyclosm = L.tileLayer("https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm-lite/{z}/{x}/{y}.png", {
      subdomains: "abc", maxZoom: 18, pane: "calqueCyclOSM",
      attribution: 'Pistes : <a href="https://www.cyclosm.org">CyclOSM</a>'
    });

    function groupe(classeCss, rayon, sansRegroupementA, attribution) {
      return L.markerClusterGroup({
        chunkedLoading: true, showCoverageOnHover: false, maxClusterRadius: rayon,
        disableClusteringAtZoom: sansRegroupementA, attribution: attribution,
        iconCreateFunction: function (c) {
          var n = c.getChildCount(), taille = n < 100 ? 32 : n < 1000 ? 40 : 48;
          return L.divIcon({ html: "<span>" + n + "</span>", className: classeCss, iconSize: [taille, taille] });
        }
      });
    }

    // --- état des bascules (infobulle + texte lu par les lecteurs d'écran)
    function indiquer(nom, message) {
      var b = boutons[nom];
      if (!b) return;
      var def = BASCULES.filter(function (x) { return x.nom === nom; })[0];
      b.title = def.aide + (message ? " — " + message : "");
      b.classList.toggle("en-attente", !!message && actifs[nom]);
      if (statut && message && actifs[nom]) statut.textContent = def.aide + " : " + message;
    }

    // --- vélos en libre-service
    function activerVLS(actif) {
      if (!actif) { if (couches.vls) carte.removeLayer(couches.vls); indiquer("vls", ""); return; }
      if (couches.vls) { carte.addLayer(couches.vls); return; }
      indiquer("vls", "chargement…");
      fetch("data/stations.json").then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      }).then(function (donnees) {
        var g = groupe("cluster-vls", 50);
        g.addLayers(donnees.stations.map(function (s) {
          var m = L.circleMarker([s[0], s[1]], { radius: 6, color: "#ffffff", weight: 1.5, fillColor: "#0e7c5a", fillOpacity: 1 });
          var velos = s[3] == null ? "disponibilité inconnue" : s[3] + (s[3] > 1 ? " vélos disponibles" : " vélo disponible");
          if (s[5] === 1) m.setStyle({ fillColor: "#ffffff", color: "#0e7c5a", weight: 2 });
          m.bindPopup("<strong>" + echapper(s[2] || "Station") + "</strong><br>" +
            (s[5] === 1 ? "Zone de stationnement d'un service en free-floating<br>" : "") + echapper(velos) +
            "<br><small>" + echapper(donnees.systemes[s[4]] || "") + "</small>");
          return m;
        }));
        couches.vls = g;
        if (actifs.vls) carte.addLayer(g);
        indiquer("vls", "");
      }).catch(function () {
        indiquer("vls", "indisponible pour le moment");
        basculer("vls", false);
      });
    }

    // --- stationnement (emplacements OpenStreetMap)
    function nomValeur(f, champ, i) { return i >= 0 ? f.valeurs[champ][i] : null; }

    function popupStationnement(f, p) {
      var k = {}; f.champs.forEach(function (c, i) { k[c] = p[i]; });
      var accroche = nomValeur(f, "accroche", k.accroche), protection = nomValeur(f, "protection", k.protection);
      var oui = function (v) { return v === 1 ? "oui" : v === 0 ? "non" : "non renseigné"; };
      var secu = accroche === "cadre" || accroche === "cadre et roue";
      var lignes = [
        "Capacité : " + (k.capacite != null ? k.capacite + " place" + (k.capacite > 1 ? "s" : "") : "non renseignée") +
          (k.capacite_cargo ? " (dont " + k.capacite_cargo + " vélo-cargo)" : ""),
        "Accroche : " + (accroche || "non renseignée"),
        nomValeur(f, "mobilier", k.mobilier) ? "Mobilier : " + nomValeur(f, "mobilier", k.mobilier) : null,
        protection && protection.indexOf("ferm") >= 0 ? "Fermé : " + protection : null,
        "Couvert : " + oui(k.couverture) + ", surveillé : " + oui(k.surveillance) + ", gratuit : " + oui(k.gratuit),
        nomValeur(f, "acces", k.acces) ? "Accès : " + nomValeur(f, "acces", k.acces) : null
      ];
      return "<strong>" + (secu ? "Stationnement sécurisé" : "Stationnement vélo") + "</strong><br>" +
        lignes.filter(Boolean).map(echapper).join("<br>") +
        "<br><small>© les contributeurs d'OpenStreetMap sous licence ODbL</small>";
    }

    function calqueStationnement() {
      if (!couches.stationnement) {
        couches.stationnement = groupe("cluster-stat", 45, 17, "Stationnement : © les contributeurs d'OpenStreetMap sous licence ODbL");
      }
      return couches.stationnement;
    }

    function majStationnement() {
      if (!actifs.stationnement) return;
      if (carte.getZoom() < ZOOM_DETAIL) { indiquer("stationnement", "zoomez sur une ville pour les voir"); return; }
      var aCharger = (options.departementsVisibles ? options.departementsVisibles() : [])
        .filter(function (d) { return !statCharges[d]; }).slice(0, 4);
      if (!aCharger.length) { indiquer("stationnement", ""); return; }
      indiquer("stationnement", "chargement…");
      Promise.all(aCharger.map(function (dep) {
        statCharges[dep] = true;
        return fichier("stationnement/" + dep + ".json").then(function (f) {
          var ia = f.champs.indexOf("accroche");
          calqueStationnement().addLayers(f.points.map(function (p) {
            var acc = nomValeur(f, "accroche", p[ia]);
            var secu = acc === "cadre" || acc === "cadre et roue";
            var m = L.circleMarker([p[0], p[1]], secu
              ? { radius: 6, color: "#ffffff", weight: 1.5, fillColor: "#1f2a2e", fillOpacity: 1 }
              : { radius: 5, color: "#1f2a2e", weight: 1.5, fillColor: "#ffffff", fillOpacity: 1 });
            m.bindPopup(function () { return popupStationnement(f, p); });
            return m;
          }));
        }).catch(function () { delete statCharges[dep]; });
      })).then(function () { indiquer("stationnement", ""); });
    }

    // --- lieux à visiter
    function iconePoi(cat) {
      return L.divIcon({ className: "icone-poi", iconSize: [26, 26], iconAnchor: [13, 13], popupAnchor: [0, -12],
        html: '<span style="background:' + POI_COULEURS[cat] + '"><svg viewBox="0 0 16 16" aria-hidden="true">' +
              POI_PICTOS[cat] + "</svg></span>" });
    }

    function popupPoi(f, p) {
      var k = {}; f.champs.forEach(function (c, i) { k[c] = p[i]; });
      var lien = k.lien && /^https?:\/\//.test(k.lien) ? '<br><a href="' + echapper(k.lien) + '" target="_blank" rel="noopener">En savoir plus</a>' : "";
      return "<strong>" + echapper(k.nom) + "</strong><br>" + echapper(f.categories[k.categorie]) +
        (k.statut ? ", " + echapper(k.statut) : "") +
        (k.description ? '<br><span class="desc-poi">' + echapper(k.description) + "</span>" : "") + lien +
        "<br><small>Source : " + echapper(f.sources[k.source]) + "</small>";
    }

    function calquePoi() {
      if (!couches.poi) {
        couches.poi = groupe("cluster-poi", 50, 16,
          "Lieux : DATAtourisme, Ministère de la Culture (Mérimée, Muséofile, jardins remarquables), Wikidata");
      }
      return couches.poi;
    }

    function chargerPoi(dep) {
      if (poiCharges[dep]) return poiCharges[dep];
      poiCharges[dep] = fichier("poi/" + dep + ".json").then(function (f) {
        calquePoi().addLayers(f.points.map(function (p) {
          var m = L.marker([p[0], p[1]], { icon: iconePoi(p[3]), title: p[2], keyboard: true });
          m.bindPopup(function () { return popupPoi(f, p); });
          m._cle = p[0] + "," + p[1] + "," + p[2];
          return m;
        }));
        return f;
      });
      poiCharges[dep].catch(function () { delete poiCharges[dep]; });
      return poiCharges[dep];
    }

    function majPoi() {
      if (!actifs.poi) return;
      var ville = options.villeActive && options.villeActive();
      if (carte.getZoom() < ZOOM_DETAIL && !ville) { indiquer("poi", "zoomez sur une ville pour les voir"); return; }
      var deps = (options.departementsVisibles ? options.departementsVisibles() : []).slice(0, 4);
      indiquer("poi", "chargement…");
      Promise.all(deps.map(function (d) { return chargerPoi(d).catch(function () { return null; }); }))
        .then(function () { indiquer("poi", ""); });
    }

    /* Ouvre le lieu (repéré par sa ligne brute dans poi/{dep}.json) en activant le calque si besoin */
    function montrerLieu(dep, brut) {
      basculer("poi", true);
      chargerPoi(dep).then(function () {
        var cle = brut[0] + "," + brut[1] + "," + brut[2], cible = null;
        calquePoi().eachLayer(function (m) { if (m._cle === cle) cible = m; });
        if (cible) calquePoi().zoomToShowLayer(cible, function () { cible.openPopup(); });
      });
    }

    // --- légendes (carte détaillée seulement)
    function majLegendes() {
      var el = options.legendes;
      if (!el) return;
      var html = "";
      if (actifs.stationnement) {
        html += '<p class="legende-calque legende-stat"><i class="pt-secu" aria-hidden="true"></i>Stationnement sécurisé (accroche cadre)' +
          '<i class="pt-simple" aria-hidden="true"></i>autre</p>';
      }
      if (actifs.poi) {
        html += '<p class="legende-calque legende-poi">' + POI_NOMS_COURTS.map(function (n, i) {
          return '<span><i style="background:' + POI_COULEURS[i] + '" aria-hidden="true"></i>' + n + "</span>";
        }).join("") + "</p>";
      }
      el.innerHTML = html;
      el.hidden = !html;
    }

    // --- bascules
    function basculer(nom, actif) {
      actifs[nom] = !!actif;
      if (boutons[nom]) boutons[nom].setAttribute("aria-pressed", actif ? "true" : "false");
      if (nom === "vls") activerVLS(actif);
      else if (nom === "cyclosm") { if (actif) couches.cyclosm.addTo(carte); else carte.removeLayer(couches.cyclosm); }
      else if (nom === "stationnement") {
        if (actif) { carte.addLayer(calqueStationnement()); majStationnement(); }
        else if (couches.stationnement) carte.removeLayer(couches.stationnement);
      } else if (nom === "poi") {
        if (actif) { carte.addLayer(calquePoi()); majPoi(); }
        else if (couches.poi) carte.removeLayer(couches.poi);
      }
      if (!actif) indiquer(nom, "");
      majLegendes();
    }

    var Controle = L.Control.extend({
      options: { position: "topright" },
      onAdd: function () {
        var div = L.DomUtil.create("div", "bascules");
        div.setAttribute("role", "group");
        div.setAttribute("aria-label", "Calques de la carte");
        BASCULES.forEach(function (b) {
          var bouton = L.DomUtil.create("button", "bascule", div);
          bouton.type = "button";
          bouton.setAttribute("aria-pressed", "false");
          bouton.title = b.aide;
          bouton.setAttribute("aria-label", b.aide);
          bouton.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true">' + b.picto + "</svg><span>" + b.libelle + "</span>";
          bouton.addEventListener("click", function () { basculer(b.nom, !actifs[b.nom]); });
          boutons[b.nom] = bouton;
        });
        statut = L.DomUtil.create("span", "visuellement-cache", div);
        statut.setAttribute("aria-live", "polite");
        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.disableScrollPropagation(div);
        return div;
      }
    });
    new Controle().addTo(carte);
    carte.on("moveend", function () { majStationnement(); majPoi(); });

    return {
      basculer: basculer,
      estActif: function (nom) { return !!actifs[nom]; },
      actualiser: function () { majStationnement(); majPoi(); },
      chargerPoi: chargerPoi,
      montrerLieu: montrerLieu,
      POI_COULEURS: POI_COULEURS
    };
  }

  window.CVF = {
    COULEURS: COULEURS, COULEUR_INDISPO: COULEUR_INDISPO,
    echapper: echapper, ordinal: ordinal, nombre: nombre, dateFr: dateFr,
    seuilsQuantiles: seuilsQuantiles, classe: classe, couleur: couleur,
    fichier: fichier, creerCarte: creerCarte, creerCalques: creerCalques
  };
})();
