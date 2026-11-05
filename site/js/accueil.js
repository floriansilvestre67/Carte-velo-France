/* Carte Vélo France — la carte (carte.html).
   Départements colorés selon le score vélo sur 20 (trois critères ;
   pour les communes, calculé par le pipeline entre toutes les communes de métropole), recherche
   de ville ou de département, fiche courte au clic avec « Plus de détails » (js/fiches.js), et les
   quatre calques (js/commun.js). */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var echapper = CVF.echapper, ordinal = CVF.ordinal, nombre = CVF.nombre;

  var ZOOM_COMMUNES = 10;     // à partir de ce zoom, les communes sont cliquables

  var etat = { geo: null, seuils: [], couches: {}, selection: null, ville: null, calqueVille: null,
               calqueCommunes: null, communesChargees: {} };

  var carte = CVF.creerCarte("carte");
  carte.zoomControl.setPosition("bottomright");
  var calques = null, recherche = null;

  function proprietes() { return etat.geo.features.map(function (f) { return f.properties; }); }
  function dep(code) { return proprietes().find(function (p) { return p.code === code; }); }
  function couleur(v) { return CVF.couleur(v, etat.seuils); }

  // ---------------------------------------------------------------- départements

  function opacite() {
    var z = carte.getZoom();
    return z <= 7 ? 0.82 : z <= 8 ? 0.6 : z <= 10 ? 0.35 : 0.15;
  }

  function style(feature) {
    var p = feature.properties;
    if (etat.ville) return { fillOpacity: 0, color: "#55636a", weight: 0.6, opacity: 0.35 };
    var choisi = p.code === etat.selection;
    return { fillColor: couleur(p.score), fillOpacity: opacite(), opacity: 1,
             color: choisi ? "#1f2a2e" : "#ffffff", weight: choisi ? 3 : 0.8 };
  }

  function recolorer() {
    etat.calqueDeps.setStyle(style);
    if (etat.selection && etat.couches[etat.selection]) etat.couches[etat.selection].bringToFront();
  }

  function dessinerDepartements() {
    etat.calqueDeps = L.geoJSON(etat.geo, {
      style: style,
      onEachFeature: function (f, couche) {
        etat.couches[f.properties.code] = couche;
        couche.bindTooltip(function () {
          var p = f.properties;
          return "<strong>" + echapper(p.nom) + "</strong>" +
            (p.score != null ? "Score vélo : " + nombre(p.score, 1) + " / 20" : "<em>Score indisponible</em>");
        }, { sticky: true, className: "info-dep", direction: "top", offset: [0, -8] });
        couche.on({
          mouseover: function () { if (!etat.ville && f.properties.code !== etat.selection) couche.setStyle({ weight: 2, color: "#1f2a2e" }); },
          mouseout: function () { couche.setStyle(style(f)); },
          click: function () { choisirDepartement(f.properties.code); }
        });
      }
    }).addTo(carte);
    carte.on("zoomend", recolorer);
    cadrerFrance();
    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        carte.invalidateSize();
        var t = carte.getSize();
        if (etat.cadrageEnAttente && t.x > 0 && t.y > 0) { etat.cadrageEnAttente = false; recadrer(); }
      }).observe($("carte"));
    }
  }

  function cadrerFrance() {
    var t = carte.getSize();
    if (!(t.x > 0 && t.y > 0)) { etat.cadrageEnAttente = true; return; }
    carte.fitBounds(etat.calqueDeps.getBounds(), { padding: [10, 10], maxZoom: 7 });
  }

  function recadrer() {
    if (etat.calqueVille) carte.fitBounds(etat.calqueVille.getBounds(), { padding: [40, 40], maxZoom: 13 });
    else if (etat.selection && etat.couches[etat.selection]) carte.fitBounds(etat.couches[etat.selection].getBounds(), { padding: [30, 30], maxZoom: 9 });
    else cadrerFrance();
  }

  function centrerSur(bornes, zoomMax) {
    var t = carte.getSize();
    if (!(t.x > 0 && t.y > 0)) { etat.cadrageEnAttente = true; return; }
    if (document.hidden) carte.fitBounds(bornes, { padding: [40, 40], maxZoom: zoomMax, animate: false });
    else carte.flyToBounds(bornes, { padding: [40, 40], maxZoom: zoomMax, duration: 0.6 });
  }

  function departementsVisibles() {
    var b = carte.getBounds(), deps = [];
    Object.keys(etat.couches).forEach(function (c) { if (b.intersects(etat.couches[c].getBounds())) deps.push(c); });
    if (etat.ville) deps.push(RechercheVille.departement(etat.ville));
    return deps.filter(function (d, i) { return deps.indexOf(d) === i; });
  }

  // ---------------------------------------------------------------- légende

  function dessinerLegende() {
    $("legende-bande").innerHTML = CVF.COULEURS.map(function (c) { return '<span style="background:' + c + '"></span>'; }).join("");
  }

  // ---------------------------------------------------------------- fiche courte

  /* « 12e sur 34 935 », « 3e ex æquo sur 96 » */
  function texteRang(rang, exAequo, sur) {
    return ordinal(rang) + (exAequo ? " ex æquo" : "") + " sur " + nombre(sur);
  }

  // Les trois critères du score vélo : aménagements, stations de vélos en libre-service, stationnement.
  // detail(cible) : dessine la fiche complète sous le bouton « Plus de détails » (au premier dépliage).
  function fiche(titre, sousTitre, score, rang, km, stations, places, detail) {
    var el = $("fiche-courte");
    var indispo = '<span class="indispo">indisponible</span>';
    el.innerHTML =
      '<div class="fiche-tete"><h2>' + echapper(titre) + (sousTitre ? ' <span class="code">' + echapper(sousTitre) + "</span>" : "") + "</h2>" +
      '<button type="button" class="bouton-fermer" id="fermer-fiche-courte" aria-label="Fermer">×</button></div>' +
      (score != null
        ? '<p class="score-court"><span class="valeur">' + nombre(score, 1) + '</span><span class="unite">/ 20</span></p>' +
          '<p class="rang-court">' + echapper(rang) + "</p>"
        : '<p class="score-court"><span class="indispo">Score vélo indisponible</span></p>') +
      "<dl>" +
      "<div><dt>Aménagements cyclables</dt><dd>" + (km != null ? nombre(km, km > 0 && km < 10 ? 1 : 0) + " km" : indispo) + "</dd></div>" +
      "<div><dt>Stations de vélos en libre-service</dt><dd>" + (stations != null ? nombre(stations) : indispo) + "</dd></div>" +
      "<div><dt>Places de stationnement vélo</dt><dd>" + (places != null ? nombre(places) : indispo) + "</dd></div>" +
      "</dl>" +
      '<button type="button" class="bouton-details" id="bouton-details" aria-expanded="false" aria-controls="detail-fiche">' +
      '<span>Plus de détails</span><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 8l5 5 5-5"/></svg></button>' +
      '<div class="fiche detail-fiche" id="detail-fiche" hidden></div>';
    el.hidden = false;
    $("fermer-fiche-courte").addEventListener("click", fermer);
    var bouton = $("bouton-details"), cible = $("detail-fiche"), dessine = false;
    var deplier = function (ouvert) {
      etat.detailOuvert = ouvert;                     // gardé d'une fiche à l'autre
      bouton.setAttribute("aria-expanded", ouvert ? "true" : "false");
      bouton.querySelector("span").textContent = ouvert ? "Moins de détails" : "Plus de détails";
      el.classList.toggle("deplie", ouvert);
      cible.hidden = !ouvert;
      if (ouvert && !dessine) { dessine = true; detail(cible); }
    };
    bouton.addEventListener("click", function () { deplier(!etat.detailOuvert); });
    if (etat.detailOuvert) deplier(true);
  }

  function fermer() {
    $("fiche-courte").hidden = true;
    if (etat.ville) choisirVille(null);
    etat.selection = null;
    if (recherche) recherche.afficher("");
    majAdresse();
    recolorer();
  }

  function choisirDepartement(code, recentrer) {
    if (etat.ville) choisirVille(null, true);
    var p = dep(code);
    if (!p) return;
    etat.selection = code;
    majAdresse();
    recolorer();
    if (recherche) recherche.afficher(p.nom);
    if (recentrer && etat.couches[code]) centrerSur(etat.couches[code].getBounds(), 9);
    // Rang parmi les départements qui ont un score ; ex æquo si un autre a exactement le même score
    var classes = proprietes().filter(function (q) { return q.score != null; });
    var egaux = classes.filter(function (q) { return q.score === p.score; }).length;
    fiche(p.nom, "(" + p.code + ")", p.score,
          p.score != null && p.rangs && p.rangs.score ? texteRang(p.rangs.score, egaux > 1, classes.length) + " départements" : null,
          p.km_total, p.vls_stations, p.stat_places,
          function (cible) { cible.innerHTML = CVF.detailDepartement(p, etat.meta, proprietes); });
  }

  // ---------------------------------------------------------------- ville

  /* Adresse partageable : ?ville=CODE_INSEE ou ?dep=CODE, et &calques=vls,poi… (calques affichés) */
  function majAdresse() {
    var q = etat.ville ? "ville=" + etat.ville : etat.selection ? "dep=" + etat.selection : "";
    var actifs = calques ? calques.actifs() : [];
    if (actifs.length) q += (q ? "&" : "") + "calques=" + actifs.join(",");
    history.replaceState(null, "", location.pathname + (q ? "?" + q : ""));
  }

  function choisirVille(code, sansFermer) {
    if (etat.calqueVille) { carte.removeLayer(etat.calqueVille); etat.calqueVille = null; }
    etat.ville = code || null;
    majAdresse();
    if (!etat.ville) {
      if (recherche) recherche.afficher("");
      if (!sansFermer) $("fiche-courte").hidden = true;
      recolorer();
      return;
    }
    var d = RechercheVille.departement(code);
    etat.selection = null;
    recolorer();
    Promise.all([CVF.fichier("communes/" + d + ".json"),
                 CVF.fichier("contours/" + d + ".geojson").catch(function () { return null; })]).then(function (res) {
      if (etat.ville !== code) return;
      var f = res[0], contours = res[1], c = f.communes[code];
      if (!c) throw new Error("commune absente");
      if (recherche) recherche.afficher(c.n || code);
      var forme = contours && contours.features.find(function (x) { return x.properties.code === code; });
      if (forme) {
        // Seule la ville est colorée (selon son score), détourée en trait gras
        etat.calqueVille = L.geoJSON(forme, { interactive: false,
          style: { color: "#1f2a2e", weight: 4, fill: true, fillColor: couleur(c.sc), fillOpacity: 0.35 } }).addTo(carte);
        centrerSur(etat.calqueVille.getBounds(), 13);
      }
      var sur = (f.score_communes || {}).sur;
      fiche(c.n || code, (dep(d) || {}).nom || "", c.sc,
            c.rg && sur ? texteRang(c.rg, c.eq > 1, sur) + " communes" : null,
            c.km ? c.km.t : null, c.vls ? c.vls.st : null, c.stat ? c.stat.p : null,
            function (cible) {
              CVF.detailVille(cible, f, code, { meta: etat.meta, depProps: dep(d), calques: calques,
                                                estToujoursAffiche: function () { return etat.ville === code; } });
            });
      if (window.matchMedia("(max-width: 700px)").matches) $("fiche-courte").focus({ preventScroll: true });
    }).catch(function () {
      var el = $("fiche-courte");
      el.innerHTML = '<p class="message-erreur" role="alert">La fiche de cette ville n\'a pas pu être chargée.</p>';
      el.hidden = false;
    });
  }

  // ---------------------------------------------------------------- communes cliquables en zoomant

  function majCommunes() {
    if (carte.getZoom() < ZOOM_COMMUNES) {
      if (etat.calqueCommunes) carte.removeLayer(etat.calqueCommunes);
      return;
    }
    if (!etat.calqueCommunes) {
      etat.calqueCommunes = L.featureGroup();
    }
    if (!carte.hasLayer(etat.calqueCommunes)) etat.calqueCommunes.addTo(carte);
    departementsVisibles().slice(0, 4).forEach(function (d) {
      if (etat.communesChargees[d]) return;
      etat.communesChargees[d] = true;
      Promise.all([CVF.fichier("contours/" + d + ".geojson"), CVF.fichier("communes/" + d + ".json")]).then(function (res) {
        var geo = res[0], noms = res[1].communes;
        L.geoJSON(geo, {
          style: { color: "#1f2a2e", weight: 0, opacity: 0, fill: true, fillOpacity: 0 },
          onEachFeature: function (f, couche) {
            var c = noms[f.properties.code] || {};
            couche.bindTooltip("<strong>" + echapper(c.n || f.properties.code) + "</strong>" +
              (c.sc != null ? "Score vélo : " + nombre(c.sc, 1) + " / 20" : "<em>Score indisponible</em>"),
              { sticky: true, className: "info-dep", direction: "top" });
            couche.on({
              mouseover: function () { couche.setStyle({ weight: 1.5, opacity: 0.8 }); },
              mouseout: function () { couche.setStyle({ weight: 0, opacity: 0 }); },
              click: function (e) { L.DomEvent.stopPropagation(e); choisirVille(f.properties.code); }
            });
          }
        }).addTo(etat.calqueCommunes);
      }).catch(function () { delete etat.communesChargees[d]; });
    });
  }

  // ---------------------------------------------------------------- pop-ups des lieux et des stations

  /* Une pop-up de la carte ne peut pas passer devant la fiche (elle est dessinée dans la carte) :
     on déplace donc la carte pour qu'elle s'ouvre dans la partie visible, à côté de la fiche
     (ordinateur) ou au-dessus d'elle (téléphone). Sur téléphone, « Plus de détails » se replie
     d'abord pour libérer de la place. */
  function placerPopupHorsFiche(e) {
    var fiche = $("fiche-courte");
    if (!fiche || fiche.hidden) return;
    var bouton = $("bouton-details");
    var telephone = window.matchMedia("(max-width: 700px)").matches;
    if (telephone && bouton && bouton.getAttribute("aria-expanded") === "true") bouton.click();
    var m = $("carte").getBoundingClientRect(), f = fiche.getBoundingClientRect();
    var marge = 12, hautGauche = [marge, marge], basDroite = [marge, marge];
    if (f.top - m.top > m.height * 0.35) {
      basDroite[1] = Math.max(marge, m.bottom - f.top + marge);       // fiche en bas (téléphone)
    } else {
      hautGauche[0] = Math.max(marge, f.right - m.left + marge);      // fiche à gauche (ordinateur)
    }
    e.popup.options.autoPanPaddingTopLeft = L.point(hautGauche);
    e.popup.options.autoPanPaddingBottomRight = L.point(basDroite);
    e.popup.update();                                                 // recalcule la position avec ces marges
  }

  // ---------------------------------------------------------------- démarrage

  Promise.all([
    fetch("data/departements.geojson").then(function (r) { if (!r.ok) throw new Error("geo"); return r.json(); }),
    fetch("data/meta.json").then(function (r) { if (!r.ok) throw new Error("meta"); return r.json(); })
  ]).then(function (res) {
    var geo = res[0];
    etat.meta = res[1];
    etat.geo = geo;
    etat.seuils = CVF.seuilsQuantiles(proprietes().map(function (p) { return p.score; }));
    dessinerDepartements();
    dessinerLegende();
    calques = CVF.creerCalques(carte, { departementsVisibles: departementsVisibles,
                                        villeActive: function () { return !!etat.ville; },
                                        surChangement: majAdresse });
    // Recherche : communes et départements (nom ou numéro)
    recherche = RechercheVille.attacher($("recherche-ville"), $("suggestions-ville"), function (v) {
      if (v.type === "departement") choisirDepartement(v.code, true);
      else choisirVille(v.entiere || v.code);
    }, { departements: function () { return proprietes().map(function (p) { return { code: p.code, nom: p.nom }; }); } });
    carte.on("moveend", majCommunes);
    carte.on("popupopen", placerPopupHorsFiche);
    // Pendant qu'une pop-up est ouverte, les infobulles de survol (département, commune) sont masquées
    carte.on("popupopen", function () { carte.getContainer().classList.add("popup-ouverte"); });
    carte.on("popupclose", function () { carte.getContainer().classList.remove("popup-ouverte"); });
    // Adresse : ?ville=…, ?dep=… ; anciens liens de la carte détaillée : #dep=…
    var q = new URLSearchParams(location.search), h = new URLSearchParams(location.hash.slice(1));
    var ville = q.get("ville"), depDemande = q.get("dep") || h.get("dep");
    // Calques demandés (cases cochées sur la page d'accueil, ou adresse partagée)
    (q.get("calques") || "").split(",").forEach(function (nom) {
      if (calques.noms.indexOf(nom) >= 0) calques.basculer(nom, true);
    });
    if (ville && /^[0-9AB]{5}$/i.test(ville)) choisirVille(ville.toUpperCase());
    else if (depDemande && dep(depDemande.toUpperCase())) choisirDepartement(depDemande.toUpperCase(), true);
  }).catch(function (e) {
    if (window.console) console.error(e);
    $("legende-simple").innerHTML = '<p class="message-erreur" role="alert">Les données n\'ont pas pu être chargées. Réessayez dans quelques minutes.</p>';
  });
})();
