/* Carte Vélo France — fiches détaillées (bouton « Plus de détails » de la carte).
   Reprend le contenu de l'ancienne carte détaillée :
     CVF.detailDepartement(p, meta, proprietes)  -> HTML : tous les indicateurs, rangs national et régional
     CVF.detailVille(cible, f, code, options)    -> remplit cible : population, aménagements par type,
                                                    stationnement, vélos en libre-service, accidents par année,
                                                    lieux à voir, lien vers les statistiques
   Nécessite js/commun.js. */
(function () {
  "use strict";

  var echapper = CVF.echapper, ordinal = CVF.ordinal, dateFr = CVF.dateFr;
  var SEUIL_RANG = 2000;   // habitants : en dessous, les rangs par habitant n'ont pas de sens
  var indispo = '<span class="indispo">indisponible</span>';

  function indicateur(meta, cle) { return meta.indicateurs.find(function (i) { return i.cle === cle; }); }

  function avecUnite(meta, valeur, cle) {
    if (valeur === null || valeur === undefined) return null;
    var ind = indicateur(meta, cle);
    return CVF.nombre(valeur, ind ? ind.decimales : 1) + " " + (ind ? ind.unite : "");
  }

  // ---------------------------------------------------------------- département

  function detailDepartement(p, meta, proprietes) {
    var tous = proprietes();
    var region = tous.filter(function (q) { return q.region && q.region === p.region; });
    var rangRegional = function (cle) {
      if (!p.region || p[cle] == null) return null;
      var v = region.filter(function (q) { return q[cle] != null; });
      return { rang: 1 + v.filter(function (q) { return q[cle] > p[cle]; }).length, sur: v.length };
    };
    var ligne = function (cle) {
      var ind = indicateur(meta, cle), v = avecUnite(meta, p[cle], cle);
      var rang = p.rangs && p.rangs[cle], rr = rangRegional(cle);
      var texteRang = rang ? ordinal(rang) + " sur " + tous.length : "";
      if (rr) texteRang += (texteRang ? ", " : "") + ordinal(rr.rang) + " sur " + rr.sur + " dans la région";
      return '<tr><th scope="row">' + echapper(ind.libelle) + "</th><td>" +
        (v ? echapper(v) + (texteRang ? '<span class="rang">' + texteRang + "</span>" : "") : indispo) + "</td></tr>";
    };
    var groupes = {};
    meta.indicateurs.forEach(function (i) {
      if (i.cle === "score") return;
      (groupes[i.groupe] = groupes[i.groupe] || []).push(i.cle);
    });
    var html = "";
    var rr = rangRegional("score");
    if (rr) html += '<p class="rang-region">Score vélo : ' + ordinal(rr.rang) + " sur " + rr.sur + " en " + echapper(p.region_nom) + "</p>";
    if (p.score != null && p.score_nb_indicateurs < meta.score_indicateurs.length) {
      html += '<p class="indispo">Score calculé sur ' + p.score_nb_indicateurs + " critères sur " +
        meta.score_indicateurs.length + " (données manquantes).</p>";
    }
    html += "<table>";
    html += '<tr class="groupe"><th scope="rowgroup" colspan="2">Population et surface</th></tr>';
    if (p.region_nom) html += '<tr><th scope="row">Région</th><td>' + echapper(p.region_nom) + "</td></tr>";
    html += '<tr><th scope="row">Population</th><td>' + (p.population != null ? CVF.nombre(p.population) + " hab." : indispo) + "</td></tr>";
    html += '<tr><th scope="row">Surface</th><td>' + (p.surface_km2 != null ? CVF.nombre(p.surface_km2) + " km²" : indispo) + "</td></tr>";
    Object.keys(groupes).forEach(function (g) {
      html += '<tr class="groupe"><th scope="rowgroup" colspan="2">' + echapper(g) + "</th></tr>";
      groupes[g].forEach(function (cle) { html += ligne(cle); });
    });
    html += "</table>";
    html += '<p><a class="lien-stats-ville" href="statistiques.html?dep=' + encodeURIComponent(p.code) + '">Voir les statistiques d\'accidents du département</a></p>';
    return html;
  }

  // ---------------------------------------------------------------- ville

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
    var k = {};
    f.accidents.champs.forEach(function (ch, i) { k[ch] = i; });
    var par = {};
    f.accidents.lignes.forEach(function (l) {
      if (l[k.com] !== code) return;
      var a = par[l[k.an]] = par[l[k.an]] || { acc: 0, tues: 0, blesses: 0 };
      a.acc++; a.tues += l[k.tues]; a.blesses += l[k.hosp] + l[k.legers];
    });
    return par;
  }

  /* Petit histogramme SVG (pas de bibliothèque de graphiques sur la carte) */
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

  /* Priorité des « incontournables » : musées de France, monuments classés, puis le reste par catégorie */
  function priorite(k) {
    if (k.statut === "musée de France") return 0;
    if (k.statut === "classé MH") return 1;
    return 2 + k.categorie + (k.statut === "inscrit MH" ? 0 : 0.5);
  }

  function dessinerLieux(cible, dep, code, calques, estToujoursAffiche) {
    CVF.fichier("poi/" + dep + ".json").then(function (f) {
      if (!estToujoursAffiche()) return;
      var lieux = f.points.map(function (p) { var k = {}; f.champs.forEach(function (c, i) { k[c] = p[i]; }); k.brut = p; return k; })
        .filter(function (k) { return k.commune === code; });
      if (!lieux.length) { cible.innerHTML = '<p class="note-ville">Aucun lieu recensé dans cette commune.</p>'; return; }
      var compte = f.categories.map(function () { return 0; });
      lieux.forEach(function (k) { compte[k.categorie]++; });
      lieux.sort(function (a, b) {
        return priorite(a) - priorite(b) || (b.description ? 1 : 0) - (a.description ? 1 : 0) || a.nom.localeCompare(b.nom, "fr");
      });
      var html = '<p class="note-ville">' + compte.map(function (n, i) {
        return n ? f.categories[i] + " : " + n : null; }).filter(Boolean).join(" ; ") + '.</p><ul class="liste-lieux">';
      lieux.slice(0, 8).forEach(function (k, i) {
        html += '<li><button type="button" data-i="' + i + '"><i style="background:' + calques.POI_COULEURS[k.categorie] + '" aria-hidden="true"></i>' +
          '<span class="nom-lieu">' + echapper(k.nom) + '</span><span class="cat-lieu">' + echapper(f.categories[k.categorie]) +
          (k.statut ? ", " + echapper(k.statut) : "") + "</span></button></li>";
      });
      cible.innerHTML = html + "</ul>" + (lieux.length > 8 ? '<p class="note-ville">Activez « À visiter » sur la carte pour voir les ' + lieux.length + " lieux.</p>" : "");
      cible.querySelectorAll("button[data-i]").forEach(function (b) {
        b.addEventListener("click", function () { calques.montrerLieu(dep, lieux[Number(b.getAttribute("data-i"))].brut); });
      });
    }).catch(function () { cible.innerHTML = '<p class="indispo">Lieux indisponibles.</p>'; });
  }

  /* options : { meta, depProps, calques, estToujoursAffiche() } */
  function detailVille(cible, f, code, options) {
    var meta = options.meta, c = f.communes[code], dep = options.depProps || {};
    var fmt0 = function (v) { return CVF.nombre(v); }, fmt1 = function (v) { return CVF.nombre(v, 1); };
    var fmt2 = function (v) { return CVF.nombre(v, 2); };
    var km = c.km ? c.km.t : null, pop = c.p;
    var ligne = function (lib, val, rang) {
      return '<tr><th scope="row">' + lib + "</th><td>" + (val == null ? indispo : echapper(val)) +
        (rang ? '<span class="rang">' + ordinal(rang.rang) + " sur " + rang.sur + " dans le département</span>" : "") + "</td></tr>";
    };
    var html = '<p class="sous-titre-ville">' + echapper(dep.nom || f.dep) + (dep.region_nom ? ", " + echapper(dep.region_nom) : "") + "</p>";
    html += "<table>";
    html += '<tr class="groupe"><th scope="rowgroup" colspan="2">Population et surface</th></tr>';
    html += ligne("Population", pop != null ? fmt0(pop) + " hab." : null);
    html += ligne("Surface", c.s != null ? fmt1(c.s) + " km²" : null);
    html += '<tr class="groupe"><th scope="rowgroup" colspan="2">Aménagements cyclables</th></tr>';
    html += ligne("Total", km != null ? fmt1(km) + " km" : null, rangDansDep(f, code, function (x) { return x.km ? x.km.t : null; }));
    html += ligne("Pour 10 000 habitants", km != null && pop ? fmt1(km / pop * 1e4) + " km" : null,
                  rangDansDep(f, code, function (x) { return x.km && x.p ? x.km.t / x.p * 1e4 : null; }));
    if (c.km) {
      [["pistes", "Pistes cyclables"], ["bandes", "Bandes cyclables"], ["voies_vertes", "Voies vertes"],
       ["double_sens", "Double-sens cyclables"], ["autres", "Autres aménagements"]].forEach(function (t) {
        if (c.km[t[0]]) html += ligne(t[1], fmt1(c.km[t[0]]) + " km");
      });
    }
    html += '<tr class="groupe"><th scope="rowgroup" colspan="2">Stationnement vélo</th></tr>';
    if (c.stat) {
      html += ligne("Places", c.stat.p != null ? fmt0(c.stat.p) : null);
      html += ligne("Pour 10 000 habitants", c.stat.p != null && pop ? fmt0(c.stat.p / pop * 1e4) : null,
                    rangDansDep(f, code, function (x) { return x.stat && x.p ? x.stat.p / x.p * 1e4 : null; }));
      html += ligne("Dont sécurisées (accroche cadre)", c.stat.s != null ? fmt0(c.stat.s) : null);
      html += ligne("Sécurisées pour 1 000 habitants", c.stat.s1000 != null ? fmt1(c.stat.s1000) : null);
      var dStat = ((meta.sources || {}).stationnement || {}).date_donnees;
      if (dStat) html += '<tr><td colspan="2" class="note-ville">Relevé officiel au ' + echapper(dateFr(dStat)) + ".</td></tr>";
    } else {
      html += ligne("Places", null);
    }
    html += '<tr class="groupe"><th scope="rowgroup" colspan="2">Vélos en libre-service</th></tr>';
    if (c.vls) {
      html += ligne("Stations", fmt0(c.vls.st));
      if (c.vls.zv) html += ligne("Zones de stationnement en free-floating", fmt0(c.vls.zv));
      html += ligne("Vélos disponibles (relevé du jour)", fmt0(c.vls.v));
    } else {
      html += ligne("Stations", null);
    }
    html += "</table>";

    // Accidents : sélecteur d'année, mini-graphique, ratios de l'année choisie
    var par = accidentsVille(f, code);
    var srcAcc = (meta.sources || {}).accidents || {};
    html += '<h3 class="titre-section-ville">Accidents de vélo</h3>';
    var liste = [];
    if (!srcAcc.statut || srcAcc.statut === "indisponible" || !srcAcc.annees) {
      html += '<p class="indispo">Données d\'accidents indisponibles.</p>';
    } else {
      for (var a = srcAcc.annees[0]; a <= srcAcc.annees[1]; a++) liste.push(a);
      html += '<div class="champ-annee"><label for="annee-ville">Année</label> <select id="annee-ville">' +
        liste.slice().reverse().map(function (x) { return '<option value="' + x + '">' + x + "</option>"; }).join("") + "</select></div>";
      html += '<div id="acc-annee"></div>';
      html += '<figure class="mini-graphe"><figcaption>Accidents par année, ' + liste[0] + "–" + liste[liste.length - 1] + "</figcaption>" +
        miniGraphe(liste, par) + "</figure>";
      html += '<details><summary>Voir les données</summary><table class="donnees-ville"><thead><tr><th scope="col">Année</th><th scope="col">Accidents</th><th scope="col">Tués</th><th scope="col">Blessés</th></tr></thead><tbody>' +
        liste.map(function (x) { var v = par[x] || { acc: 0, tues: 0, blesses: 0 };
          return '<tr><th scope="row">' + x + "</th><td>" + v.acc + "</td><td>" + v.tues + "</td><td>" + v.blesses + "</td></tr>"; }).join("") +
        "</tbody></table></details>";
      html += '<p class="note-ville">Accidents corporels constatés par les forces de l\'ordre (fichiers BAAC de l\'ONISR).</p>';
    }
    html += '<h3 class="titre-section-ville">Lieux à voir</h3><div class="lieux-ville"><p class="indispo">Chargement…</p></div>';
    html += '<p><a class="lien-stats-ville" href="statistiques.html?ville=' + encodeURIComponent(code) + '">Voir toutes les statistiques de cette ville</a></p>';
    cible.innerHTML = html;

    dessinerLieux(cible.querySelector(".lieux-ville"), f.dep, code, options.calques, options.estToujoursAffiche);
    var sel = cible.querySelector("#annee-ville");
    if (sel) {
      var majAnnee = function () {
        var an = Number(sel.value), v = par[an] || { acc: 0, tues: 0, blesses: 0 };
        cible.querySelector("#acc-annee").innerHTML = "<table>" +
          ligne("Accidents en " + an, fmt0(v.acc)) +
          ligne("Cyclistes tués", fmt0(v.tues)) +
          ligne("Cyclistes blessés", fmt0(v.blesses)) +
          ligne("Pour 100 000 habitants", pop ? fmt1(v.acc / pop * 1e5) + (v.acc < 10 ? "*" : "") : null) +
          ligne("Pour 100 km d'aménagements", km ? fmt2(v.acc / km * 100) + (v.acc < 10 ? "*" : "") : null) +
          "</table>" + (v.acc < 10 ? '<p class="note-ville">* Moins de 10 accidents cette année-là : ratio peu significatif.</p>' : "");
        cible.querySelectorAll(".mini-graphe rect[data-an]").forEach(function (r) {
          r.setAttribute("class", Number(r.getAttribute("data-an")) === an ? "barre-active" : "");
        });
      };
      sel.value = liste[liste.length - 1];
      sel.addEventListener("change", majAnnee);
      majAnnee();
    }
  }

  CVF.detailDepartement = detailDepartement;
  CVF.detailVille = detailVille;
})();
