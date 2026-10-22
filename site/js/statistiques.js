/* Carte Vélo France — page « Statistiques » (accidents de vélo).

   Données (produites par scripts/construire_donnees.py) :
     data/accidents/national.json   agrégats France, régions, départements, par année
     data/communes/{dep}.json       une ligne compacte par accident (chargé à la demande)

   Filtres synchronisés avec l'adresse : ?region=84&dep=63&ville=63113&arr=&debut=2019&fin=2023
*/
(function () {
  "use strict";

  // Couleurs validées (outil dataviz) : rampe ordinale bleue pour la gravité, du plus grave au moins grave.
  var C_GRAV = ["#0d366b", "#1c5cab", "#3987e5", "#86b6ef", "#c4c8c6"];
  var C_SERIE1 = "#2a78d6", C_SERIE2 = "#eb6834";
  var C_GRILLE = "#e3e8e6", C_TEXTE = "#55636a";

  var etat = {
    nat: null, annees: [], region: "", dep: "", ville: "", arr: "", debut: null, fin: null,
    niveau: "dep", fichiers: {}, graphes: {}, tri: { cle: "parhab", sens: -1 }
  };
  var $ = function (id) { return document.getElementById(id); };
  var fmt0 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
  var fmt1 = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  var fmt2 = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function echapper(t) { var d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; }
  function somme(t) { return t.reduce(function (s, x) { return s + x; }, 0); }
  function plage(t) { return t.slice(etat.i0, etat.i1 + 1); }
  function nbAnnees() { return etat.i1 - etat.i0 + 1; }
  function nf(v, f) { return v == null || !isFinite(v) ? "indisponible" : (f || fmt0).format(v); }

  // ---------------------------------------------------------------- données

  function charger(url) {
    return fetch(url).then(function (r) { if (!r.ok) throw new Error(url + " : " + r.status); return r.json(); });
  }

  function fichierDep(dep) {
    if (!etat.fichiers[dep]) etat.fichiers[dep] = charger("data/communes/" + dep + ".json");
    return etat.fichiers[dep];
  }

  function depDeCommune(code) {
    if (!code) return "";
    if (code.slice(0, 2) === "2A" || code.slice(0, 2) === "2B") return code.slice(0, 2);
    return code.slice(0, 2) === "97" ? code.slice(0, 3) : code.slice(0, 2);
  }

  /* Même structure que les zones du fichier national, calculée à partir des lignes d'accidents. */
  function agregerLignes(lignes, champs) {
    var lib = etat.nat.libelles, n = etat.annees.length;
    var vide = function () { var t = []; for (var i = 0; i < n; i++) t.push(0); return t; };
    var matrice = function (a, b) {
      var t = []; for (var i = 0; i < n; i++) { var l = []; for (var j = 0; j < a; j++) l.push(b ? new Array(b).fill(0) : 0); t.push(l); } return t;
    };
    var ng = lib.gravite.length;
    var z = { acc: vide(), tues: vide(), hosp: vide(), legers: vide(), indemnes: vide(), nr: vide(),
              grav: matrice(ng), veh: matrice(lib.vehicule.length, ng), traj: matrice(lib.trajet.length),
              situ: matrice(lib.situ.length, ng) };
    var k = {}; champs.forEach(function (c, i) { k[c] = i; });
    lignes.forEach(function (l) {
      var i = etat.annees.indexOf(l[k.an]);
      if (i < 0) return;
      var g = l[k.gravite];
      z.acc[i]++; z.tues[i] += l[k.tues]; z.hosp[i] += l[k.hosp]; z.legers[i] += l[k.legers];
      z.indemnes[i] += l[k.indemnes]; z.nr[i] += l[k.gravite_nr];
      z.grav[i][g]++; z.veh[i][l[k.vehicule]][g]++; z.traj[i][l[k.trajet]]++; z.situ[i][l[k.situ]][g]++;
    });
    return z;
  }

  /* Zone sélectionnée : {type, code, nom, z (agrégats), info (pop, km)} — promesse. */
  function zoneCourante() {
    var nat = etat.nat;
    if (etat.ville) {
      return fichierDep(depDeCommune(etat.ville)).then(function (f) {
        var champs = f.accidents.champs, ic = champs.indexOf("com"), ia = champs.indexOf("arr");
        var lignes = f.accidents.lignes.filter(function (l) {
          return l[ic] === etat.ville && (!etat.arr || l[ia] === etat.arr);
        });
        var c = f.communes[etat.ville] || {};
        var nom = (c.n || etat.ville) + (etat.arr ? ", " + nomArrondissement(etat.arr) : "");
        return { type: "ville", code: etat.ville, nom: nom, z: agregerLignes(lignes, champs),
                 info: { pop: etat.arr ? null : c.p, km: etat.arr ? null : (c.km || {}).t }, fichier: f };
      });
    }
    var code = etat.dep ? "D" + etat.dep : etat.region ? "R" + etat.region : "FR";
    var info = nat.zones_info[code] || {};
    return Promise.resolve({ type: code === "FR" ? "FR" : code[0], code: code, nom: info.nom || code, z: nat.zones[code] || null, info: info });
  }

  function nomArrondissement(arr) {
    var n = parseInt(arr.slice(-2), 10);
    return (n === 1 ? "1er" : n + "e") + " arrondissement";
  }

  // ---------------------------------------------------------------- filtres

  function option(sel, valeur, texte) {
    var o = document.createElement("option"); o.value = valeur; o.textContent = texte; sel.appendChild(o);
  }

  function zonesDe(prefixe) {
    var zi = etat.nat.zones_info;
    return Object.keys(zi).filter(function (k) { return k[0] === prefixe; })
      .map(function (k) { return { code: k.slice(1), nom: zi[k].nom, parent: zi[k].parent }; })
      .sort(function (a, b) { return a.nom.localeCompare(b.nom, "fr"); });
  }

  function remplirDeps() {
    var sel = $("f-dep");
    sel.innerHTML = "";
    option(sel, "", "Tous");
    zonesDe("D").filter(function (d) { return !etat.region || d.parent === "R" + etat.region; })
      .forEach(function (d) { option(sel, d.code, d.nom + " (" + d.code + ")"); });
    sel.value = etat.dep;
  }

  /* Affiche le nom de la ville choisie dans le champ de recherche. */
  function remplirCommunes() {
    if (!etat.ville) { recherche.afficher(""); return Promise.resolve(); }
    return fichierDep(depDeCommune(etat.ville)).then(function (f) {
      recherche.afficher((f.communes[etat.ville] || {}).n || etat.ville);
    }).catch(function () { recherche.afficher(etat.ville); });
  }

  var recherche = { afficher: function () {} };

  function remplirArrondissements() {
    var bloc = $("bloc-arr"), sel = $("f-arr");
    var plm = { "75056": 1, "69123": 1, "13055": 1 };
    if (!etat.ville || !plm[etat.ville]) { bloc.hidden = true; etat.arr = ""; return Promise.resolve(); }
    return fichierDep(depDeCommune(etat.ville)).then(function (f) {
      var ia = f.accidents.champs.indexOf("arr"), ic = f.accidents.champs.indexOf("com"), vus = {};
      f.accidents.lignes.forEach(function (l) { if (l[ic] === etat.ville && l[ia]) vus[l[ia]] = 1; });
      sel.innerHTML = "";
      option(sel, "", "Toute la commune");
      Object.keys(vus).sort().forEach(function (a) { option(sel, a, nomArrondissement(a)); });
      sel.value = etat.arr;
      bloc.hidden = Object.keys(vus).length === 0;
    });
  }

  function remplirAnnees() {
    [$("f-debut"), $("f-fin")].forEach(function (sel) {
      sel.innerHTML = "";
      etat.annees.forEach(function (a) { option(sel, a, a); });
    });
  }

  function lireAdresse() {
    var p = new URLSearchParams(location.search);
    var a = etat.annees, der = a[a.length - 1];
    etat.region = p.get("region") || "";
    etat.dep = p.get("dep") || "";
    etat.ville = p.get("ville") || "";
    etat.arr = p.get("arr") || "";
    if (etat.ville && !etat.dep) etat.dep = depDeCommune(etat.ville);
    var zi = etat.nat.zones_info;
    if (etat.dep && !zi["D" + etat.dep]) { etat.dep = ""; etat.ville = ""; }
    if (etat.dep && !etat.region && zi["D" + etat.dep].parent) etat.region = zi["D" + etat.dep].parent.slice(1);
    if (etat.region && !zi["R" + etat.region]) etat.region = "";
    // Période par défaut : les 5 dernières années disponibles
    var debut = parseInt(p.get("debut"), 10), fin = parseInt(p.get("fin"), 10);
    etat.fin = a.indexOf(fin) >= 0 ? fin : der;
    etat.debut = a.indexOf(debut) >= 0 ? debut : Math.max(a[0], etat.fin - 4);
    if (etat.debut > etat.fin) etat.debut = etat.fin;
  }

  function majAdresse() {
    var p = new URLSearchParams();
    if (etat.region) p.set("region", etat.region);
    if (etat.dep) p.set("dep", etat.dep);
    if (etat.ville) p.set("ville", etat.ville);
    if (etat.arr) p.set("arr", etat.arr);
    p.set("debut", etat.debut);
    p.set("fin", etat.fin);
    history.replaceState(null, "", "?" + p.toString());
    // Lien vers la carte en gardant la zone
    var h = new URLSearchParams();
    if (etat.ville) h.set("ville", etat.ville);
    var hash = etat.dep ? "#dep=" + etat.dep : etat.region ? "#reg=" + etat.region : "";
    $("lien-carte").href = "./" + (h.toString() ? "?" + h.toString() : "") + hash;
  }

  function synchroniserControles() {
    $("f-region").value = etat.region;
    remplirDeps();
    $("f-debut").value = etat.debut;
    $("f-fin").value = etat.fin;
    etat.i0 = etat.annees.indexOf(etat.debut);
    etat.i1 = etat.annees.indexOf(etat.fin);
  }

  // ---------------------------------------------------------------- rendu général

  function rendre() {
    synchroniserControles();
    majAdresse();
    return remplirCommunes().then(remplirArrondissements).then(zoneCourante).then(function (zone) {
      etat.zone = zone;
      var periode = etat.debut === etat.fin ? "en " + etat.debut : "de " + etat.debut + " à " + etat.fin;
      $("titre").textContent = "Accidents de vélo : " + zone.nom;
      $("sous-titre").textContent = "Cyclistes impliqués dans un accident corporel " + periode +
        (zone.type === "FR" ? ", France métropolitaine." : ".");
      document.title = "Accidents de vélo : " + zone.nom + " – Carte Vélo France";
      if (!zone.z) {
        $("alertes").innerHTML = '<div class="alerte" role="alert"><strong>Aucune donnée</strong>Aucun accident n\'est recensé pour cette zone.</div>';
        return;
      }
      majAlertes(zone);
      majChiffres(zone);
      if (window.Chart) {
        majEvolution(zone);
        majVehicules(zone);
        majMotifs(zone);
        majSituations(zone);
        majPiste(zone);
      }
      return majRatios(zone).then(function () { return majCorrelations(zone); });
    }).catch(function (e) {
      if (window.console) console.error(e);
      $("alertes").innerHTML = '<div class="alerte" role="alert"><strong>Données indisponibles</strong>' +
        "Les données n'ont pas pu être chargées. Elles sont recalculées chaque jour : réessayez plus tard.</div>";
    });
  }

  function majAlertes(zone) {
    var html = "";
    var total = somme(plage(zone.z.acc));
    if (total < 30) {
      html += '<div class="alerte faible"><strong>Effectifs faibles</strong>' + fmt0.format(total) +
        " accident" + (total > 1 ? "s" : "") + " sur la période : les chiffres sont affichés, mais ils varient beaucoup " +
        "d'une année à l'autre. Élargissez la période ou la zone avant d'en tirer une conclusion.</div>";
    }
    (etat.nat.ruptures || []).forEach(function (r) {
      var debut = r.annees[0], fin = r.annees[1] || 9999;
      if (etat.fin >= debut && etat.debut <= fin) {
        html += '<div class="alerte"><strong>Rupture de série à partir de ' + debut + "</strong>" + echapper(r.texte) + "</div>";
      }
    });
    if (!window.Chart) {
      html += '<div class="alerte"><strong>Graphiques indisponibles</strong>La bibliothèque de graphiques n\'a pas pu être chargée. Les tableaux de données restent consultables.</div>';
    }
    $("alertes").innerHTML = html;
  }

  function majChiffres(zone) {
    var z = zone.z, n = nbAnnees();
    var acc = somme(plage(z.acc));
    var items = [
      [acc, "accidents"],
      [somme(plage(z.tues)), "cyclistes tués"],
      [somme(plage(z.hosp)), "blessés hospitalisés"],
      [somme(plage(z.legers)), "blessés légers"]
    ];
    if (n > 1) items.push([acc / n, "accidents par an en moyenne", fmt1]);
    $("chiffres").innerHTML = items.map(function (it) {
      return '<div class="chiffre"><span class="valeur">' + (it[2] || fmt0).format(it[0]) +
        '</span><span class="libelle">' + it[1] + "</span></div>";
    }).join("");
  }

  // ---------------------------------------------------------------- graphiques

  window.Chart && (function () {
    Chart.defaults.font.family = '"Atkinson Hyperlegible", system-ui, sans-serif';
    Chart.defaults.font.size = 13;
    Chart.defaults.color = C_TEXTE;
    Chart.defaults.animation = false;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
    Chart.defaults.plugins.legend.labels.boxHeight = 12;
    Chart.defaults.plugins.tooltip.callbacks.label = function (ctx) {
      var v = ctx.parsed.x != null && ctx.chart.options.indexAxis === "y" ? ctx.parsed.x : ctx.parsed.y;
      return (ctx.dataset.label ? ctx.dataset.label + " : " : "") + fmt0.format(v);
    };
  })();

  /* Bande grisée sur les années de série incomplète (2018 et après), avec une mention. */
  var bandeRupture = {
    id: "bandeRupture",
    beforeDatasetsDraw: function (chart, args, opts) {
      if (!opts || !opts.depuis) return;
      var x = chart.scales.x, labels = chart.data.labels, i = labels.indexOf(opts.depuis);
      if (i < 0) { if (labels[0] > opts.depuis) i = 0; else return; }
      var ca = chart.chartArea, ctx = chart.ctx;
      var gauche = i === 0 ? ca.left : (x.getPixelForValue(i - 1) + x.getPixelForValue(i)) / 2;
      ctx.save();
      ctx.fillStyle = "rgba(85, 99, 106, 0.08)";
      ctx.fillRect(gauche, ca.top, ca.right - gauche, ca.bottom - ca.top);
      ctx.fillStyle = C_TEXTE;
      ctx.font = "12px " + Chart.defaults.font.family;
      ctx.textAlign = "right";
      ctx.fillText("Série incomplète", ca.right - 4, ca.top + 12);
      ctx.restore();
    }
  };

  function graphe(id, config) {
    if (etat.graphes[id]) etat.graphes[id].destroy();
    etat.graphes[id] = new Chart($(id), config);
  }

  function axes(opts) {
    opts = opts || {};
    return {
      x: Object.assign({ grid: { display: false }, border: { color: C_GRILLE }, stacked: !!opts.stacked }, opts.x || {}),
      y: Object.assign({ beginAtZero: true, grid: { color: C_GRILLE }, border: { display: false }, stacked: !!opts.stacked,
                         ticks: { precision: 0 } }, opts.y || {})
    };
  }

  function tableHTML(entetes, lignes) {
    return "<table><thead><tr>" + entetes.map(function (e, i) {
      return '<th scope="col">' + echapper(e) + "</th>";
    }).join("") + "</tr></thead><tbody>" + lignes.map(function (l) {
      return "<tr>" + l.map(function (c, i) {
        return i === 0 ? '<th scope="row">' + echapper(c) + "</th>" : "<td>" + (typeof c === "number" ? fmt0.format(c) : echapper(c)) + "</td>";
      }).join("") + "</tr>";
    }).join("") + "</tbody></table>";
  }

  function majEvolution(zone) {
    var z = zone.z, a = etat.annees;
    // Une seule année choisie : on montre toute la série, l'année choisie mise en avant.
    var i0 = etat.i0, i1 = etat.i1, seule = i0 === i1;
    if (seule) { i0 = 0; i1 = a.length - 1; }
    var lab = a.slice(i0, i1 + 1);
    var tranche = function (t) { return t.slice(i0, i1 + 1); };
    var blesses = z.hosp.map(function (h, i) { return h + z.legers[i]; });
    var rayon = function (ctx) { return seule && lab[ctx.dataIndex] === etat.debut ? 6 : 3; };
    $("aide-evolution").textContent = seule
      ? "Toute la série est affichée ; l'année " + etat.debut + " est mise en avant."
      : "Années " + lab[0] + " à " + lab[lab.length - 1] + ".";
    var ligne = function (label, data, c) {
      return { label: label, data: data, borderColor: c, backgroundColor: c, borderWidth: 2,
               pointRadius: rayon, pointHoverRadius: 7, tension: 0 };
    };
    var opts = { plugins: { bandeRupture: { depuis: 2018 }, tooltip: { mode: "index", intersect: false } },
                 interaction: { mode: "index", intersect: false }, scales: axes() };
    graphe("g-evolution", { type: "line", plugins: [bandeRupture],
      data: { labels: lab, datasets: [ligne("Accidents", tranche(z.acc), C_SERIE1),
                                      ligne("Cyclistes blessés", tranche(blesses), C_SERIE2)] },
      options: opts });
    graphe("g-tues", { type: "line", plugins: [bandeRupture],
      data: { labels: lab, datasets: [ligne("Cyclistes tués", tranche(z.tues), C_SERIE1)] },
      options: Object.assign({}, opts, { plugins: Object.assign({}, opts.plugins, { legend: { display: false } }) }) });
    $("d-evolution").innerHTML = tableHTML(
      ["Année", "Accidents", "Tués", "Blessés hospitalisés", "Blessés légers", "Indemnes", "Gravité non renseignée"],
      lab.map(function (an, j) {
        var i = i0 + j; return [String(an), z.acc[i], z.tues[i], z.hosp[i], z.legers[i], z.indemnes[i], z.nr[i]];
      }));
  }

  /* Somme sur la période d'une matrice [année][catégorie][gravité] -> [catégorie][gravité] */
  function sommeMatrice(m) {
    var res = m[0].map(function (l) { return l.map(function () { return 0; }); });
    plage(m).forEach(function (an) { an.forEach(function (l, c) { l.forEach(function (v, g) { res[c][g] += v; }); }); });
    return res;
  }

  function barresEmpilees(id, libelles, m, idTable, titreCol) {
    var lib = etat.nat.libelles;
    var ordre = libelles.map(function (_, i) { return i; })
      .filter(function (i) { return somme(m[i]) > 0; })
      .sort(function (a, b) { return somme(m[b]) - somme(m[a]); });
    var datasets = lib.gravite.map(function (g, gi) {
      return { label: g, data: ordre.map(function (i) { return m[i][gi]; }), backgroundColor: C_GRAV[gi],
               borderColor: "#ffffff", borderWidth: { right: 2 }, borderSkipped: false, barPercentage: 0.75 };
    }).filter(function (d) { return somme(d.data) > 0; });
    graphe(id, { type: "bar",
      data: { labels: ordre.map(function (i) { return libelles[i]; }), datasets: datasets },
      options: { indexAxis: "y", scales: axes({ stacked: true, x: { grid: { color: C_GRILLE }, border: { display: false }, ticks: { precision: 0 } },
                                                 y: { grid: { display: false }, beginAtZero: true } }),
                 plugins: { tooltip: { mode: "index", intersect: false,
                   callbacks: { footer: function (items) { return "Total : " + fmt0.format(somme(items.map(function (x) { return x.parsed.x; }))); } } } } } });
    $(idTable).innerHTML = tableHTML([titreCol].concat(lib.gravite, ["Total"]),
      ordre.map(function (i) { return [libelles[i]].concat(m[i], [somme(m[i])]); }));
  }

  function majVehicules(zone) {
    barresEmpilees("g-vehicules", etat.nat.libelles.vehicule, sommeMatrice(zone.z.veh), "d-vehicules", "Autre usager");
  }

  function majSituations(zone) {
    barresEmpilees("g-situ", etat.nat.libelles.situ, sommeMatrice(zone.z.situ), "d-situ", "Situation");
  }

  function majMotifs(zone) {
    var lib = etat.nat.libelles.trajet;
    var tot = lib.map(function (_, t) { return somme(plage(zone.z.traj).map(function (an) { return an[t]; })); });
    var ordre = tot.map(function (_, i) { return i; }).filter(function (i) { return tot[i] > 0; })
      .sort(function (a, b) { return tot[b] - tot[a]; });
    graphe("g-motifs", { type: "bar",
      data: { labels: ordre.map(function (i) { return lib[i]; }),
              datasets: [{ label: "Accidents", data: ordre.map(function (i) { return tot[i]; }), backgroundColor: C_SERIE1,
                           borderRadius: 4, borderSkipped: "start", barPercentage: 0.7 }] },
      options: { indexAxis: "y", plugins: { legend: { display: false } },
                 scales: axes({ x: { grid: { color: C_GRILLE }, border: { display: false }, ticks: { precision: 0 } },
                                y: { grid: { display: false } } }) } });
    $("d-motifs").innerHTML = tableHTML(["Motif", "Accidents"], ordre.map(function (i) { return [lib[i], tot[i]]; }));
  }

  function majPiste(zone) {
    var z = zone.z, a = etat.annees;
    var i0 = etat.i0, i1 = etat.i1;
    if (i1 - i0 < 2) { i0 = 0; i1 = a.length - 1; }   // moins de 3 ans : toute la série
    var lab = [], parts = [], lignes = [];
    for (var i = i0; i <= i1; i++) {
      var piste = somme(z.situ[i][1]), acc = z.acc[i];
      lab.push(a[i]);
      parts.push(acc ? Math.round(piste / acc * 1000) / 10 : null);
      lignes.push([String(a[i]), piste, acc, acc ? fmt1.format(piste / acc * 100) + " %" : "indisponible"]);
    }
    graphe("g-piste", { type: "line", plugins: [bandeRupture],
      data: { labels: lab, datasets: [{ label: "Part sur piste cyclable", data: parts, borderColor: C_SERIE1,
              backgroundColor: C_SERIE1, borderWidth: 2, pointRadius: 3, spanGaps: false }] },
      options: { plugins: { legend: { display: false }, bandeRupture: { depuis: 2018 },
                            tooltip: { callbacks: { label: function (c) { return fmt1.format(c.parsed.y) + " % des accidents"; } } } },
                 scales: axes({ y: { ticks: { callback: function (v) { return v + " %"; } } } }) } });
    $("d-piste").innerHTML = tableHTML(["Année", "Accidents sur piste cyclable", "Accidents", "Part"], lignes);
  }

  // ---------------------------------------------------------------- ratios (tableau classable)

  function ligneRatio(code, nom, accPeriode, pop, km, selection) {
    var n = nbAnnees(), parAn = accPeriode / n;
    return { code: code, nom: nom, acc: accPeriode, paran: parAn,
             parhab: pop ? parAn / pop * 1e5 : null, parkm: km ? parAn / km * 100 : null,
             km: km, pop: pop, selection: !!selection };
  }

  function majRatios(zone) {
    var nat = etat.nat, n = nbAnnees(), lignes = [], promesse = Promise.resolve();
    var accZone = function (code) { var z = nat.zones[code]; return z ? somme(plage(z.acc)) : 0; };
    var aide = "Moyennes annuelles sur la période. La population et les km d'aménagements sont les valeurs actuelles. ";
    if (zone.type === "FR" || zone.type === "R") {
      zonesDe("D").filter(function (d) { return zone.type === "FR" || d.parent === zone.code; }).forEach(function (d) {
        var i = nat.zones_info["D" + d.code];
        lignes.push(ligneRatio(d.code, d.nom, accZone("D" + d.code), i.pop, i.km));
      });
      aide += "Une ligne par département.";
    } else {
      var dep = zone.type === "D" ? zone.code.slice(1) : depDeCommune(zone.code);
      promesse = fichierDep(dep).then(function (f) {
        var champs = f.accidents.champs, ia = champs.indexOf("an"), ic = champs.indexOf("com"), par = {};
        f.accidents.lignes.forEach(function (l) {
          if (l[ia] >= etat.debut && l[ia] <= etat.fin && l[ic]) par[l[ic]] = (par[l[ic]] || 0) + 1;
        });
        Object.keys(par).forEach(function (c) {
          var info = f.communes[c] || {};
          lignes.push(ligneRatio(c, info.n || c, par[c], info.p, (info.km || {}).t, c === etat.ville));
        });
        if (zone.type === "ville" && !par[etat.ville]) {
          var info = f.communes[etat.ville] || {};
          lignes.push(ligneRatio(etat.ville, info.n || etat.ville, 0, info.p, (info.km || {}).t, true));
        }
      });
      aide += "Une ligne par commune ayant au moins un accident sur la période, avec le total du département pour comparaison.";
      promesse = promesse.then(function () {
        var i = nat.zones_info["D" + dep];
        lignes.push(ligneRatio("D" + dep, "Département : " + i.nom, accZone("D" + dep), i.pop, i.km, zone.type === "D"));
      });
    }
    return promesse.then(function () {
      var fr = nat.zones_info.FR;
      lignes.push(ligneRatio("FR", "France métropolitaine", accZone("FR"), fr.pop, fr.km, zone.type === "FR"));
      $("aide-ratios").textContent = aide + " Les valeurs suivies de « * » reposent sur moins de 10 accidents.";
      etat.lignesRatios = lignes;
      dessinerRatios();
    });
  }

  var COLONNES = [
    { cle: "nom", titre: "Zone" },
    { cle: "acc", titre: "Accidents sur la période" },
    { cle: "paran", titre: "Accidents par an", f: fmt1 },
    { cle: "parhab", titre: "Pour 100 000 hab. par an", f: fmt1 },
    { cle: "parkm", titre: "Pour 100 km d'aménagements par an", f: fmt2 },
    { cle: "km", titre: "Km d'aménagements" },
    { cle: "pop", titre: "Population" }
  ];

  function dessinerRatios() {
    var t = etat.tri, lignes = etat.lignesRatios.slice();
    var fixes = lignes.filter(function (l) { return l.code === "FR" || l.code[0] === "D" && l.nom.indexOf("Département : ") === 0; });
    var autres = lignes.filter(function (l) { return fixes.indexOf(l) < 0; });
    autres.sort(function (a, b) {
      var x = a[t.cle], y = b[t.cle];
      if (t.cle === "nom") return t.sens * String(x).localeCompare(String(y), "fr");
      if (x == null) return 1;
      if (y == null) return -1;
      return t.sens * (x - y);
    });
    var html = "<thead><tr>" + COLONNES.map(function (c) {
      var tri = t.cle === c.cle ? (t.sens < 0 ? "descending" : "ascending") : "none";
      return '<th scope="col" aria-sort="' + tri + '"><button type="button" data-cle="' + c.cle + '">' + c.titre + "</button></th>";
    }).join("") + "</tr></thead><tbody>";
    autres.concat(fixes).forEach(function (l) {
      var peu = l.acc < 10;
      html += '<tr class="' + (l.selection ? "selection" : "") + '">' + COLONNES.map(function (c, i) {
        var v = l[c.cle];
        if (i === 0) return '<th scope="row">' + echapper(v) + "</th>";
        var txt = v == null ? "indisponible" : (c.f || fmt0).format(v);
        if (peu && (c.cle === "paran" || c.cle === "parhab" || c.cle === "parkm") && v != null) txt += "*";
        return '<td class="' + (peu ? "peu" : "") + '">' + txt + "</td>";
      }).join("") + "</tr>";
    });
    $("t-ratios-table").innerHTML = html + "</tbody>";
    $("t-ratios-table").querySelectorAll("thead button").forEach(function (b) {
      b.addEventListener("click", function () {
        var cle = b.getAttribute("data-cle");
        etat.tri = { cle: cle, sens: etat.tri.cle === cle ? -etat.tri.sens : (cle === "nom" ? 1 : -1) };
        dessinerRatios();
      });
    });
  }

  // ---------------------------------------------------------------- corrélations

  function pearson(x, y) {
    var n = x.length; if (n < 3) return null;
    var mx = somme(x) / n, my = somme(y) / n, sxy = 0, sxx = 0, syy = 0;
    for (var i = 0; i < n; i++) { var dx = x[i] - mx, dy = y[i] - my; sxy += dx * dy; sxx += dx * dx; syy += dy * dy; }
    return sxx && syy ? sxy / Math.sqrt(sxx * syy) : null;
  }

  function rangs(t) {
    var idx = t.map(function (v, i) { return i; }).sort(function (a, b) { return t[a] - t[b]; });
    var r = new Array(t.length), i = 0;
    while (i < idx.length) {
      var j = i;
      while (j + 1 < idx.length && t[idx[j + 1]] === t[idx[i]]) j++;
      for (var k = i; k <= j; k++) r[idx[k]] = (i + j) / 2 + 1;
      i = j + 1;
    }
    return r;
  }

  function spearman(x, y) { return pearson(rangs(x), rangs(y)); }

  function forceCorrelation(r) {
    var a = Math.abs(r);
    return a >= 0.7 ? "forte" : a >= 0.4 ? "modérée" : a >= 0.2 ? "faible" : "très faible ou nulle";
  }

  function pointsCorrelation(zone) {
    var nat = etat.nat, n = nbAnnees(), pts = [];
    if (etat.niveau === "dep") {
      zonesDe("D").forEach(function (d) {
        var i = nat.zones_info["D" + d.code], z = nat.zones["D" + d.code];
        if (!i.pop || i.km == null) return;
        var sel = zone.type === "R" ? d.parent === zone.code : zone.type === "D" ? "D" + d.code === zone.code
          : zone.type === "ville" ? d.code === depDeCommune(zone.code) : false;
        // Pas de zone dans le fichier = aucun accident recensé
        pts.push({ nom: d.nom, acc: z ? somme(plage(z.acc)) / n : 0, pop: i.pop, km: i.km, sel: sel });
      });
    } else {
      var g = nat.grandes_communes || {};
      var deps = zone.type === "R" ? zonesDe("D").filter(function (d) { return d.parent === zone.code; }).map(function (d) { return d.code; }) : null;
      Object.keys(g).forEach(function (c) {
        var v = g[c];
        if (zone.type === "D" && v.d !== zone.code.slice(1)) return;
        if (zone.type === "ville" && v.d !== depDeCommune(zone.code)) return;
        if (deps && deps.indexOf(v.d) < 0) return;
        if (!v.p || v.km == null) return;
        pts.push({ nom: v.n, acc: somme(plage(v.acc)) / n, pop: v.p, km: v.km, sel: c === etat.ville });
      });
    }
    return pts;
  }

  function nuage(id, idCoef, pts, fx, fy, titreX, titreY) {
    var x = pts.map(fx), y = pts.map(fy);
    var groupes = [
      { label: "Zone sélectionnée", data: [], backgroundColor: C_SERIE2, pointRadius: 6 },
      { label: etat.niveau === "dep" ? "Autres départements" : "Autres communes", data: [], backgroundColor: "rgba(42, 120, 214, 0.55)", pointRadius: 4 }
    ];
    pts.forEach(function (p, i) { groupes[p.sel ? 0 : 1].data.push({ x: x[i], y: y[i], nom: p.nom }); });
    var ds = groupes.filter(function (gr) { return gr.data.length; }).map(function (gr) {
      return Object.assign(gr, { borderColor: "#ffffff", borderWidth: 1, pointHoverRadius: 8 });
    });
    graphe(id, { type: "scatter", data: { datasets: ds },
      options: { plugins: { legend: { display: ds.length > 1 },
                            tooltip: { callbacks: { label: function (c) {
                              return c.raw.nom + " : " + fmt1.format(c.raw.x) + " ; " + fmt1.format(c.raw.y); } } } },
                 scales: { x: { title: { display: true, text: titreX }, grid: { color: C_GRILLE }, border: { display: false }, beginAtZero: true },
                           y: { title: { display: true, text: titreY }, grid: { color: C_GRILLE }, border: { display: false }, beginAtZero: true } } } });
    var rp = pearson(x, y), rs = spearman(x, y);
    $(idCoef).textContent = rp == null ? "Coefficients indisponibles (trop peu de points)."
      : "Pearson r = " + fmt2.format(rp) + ", Spearman ρ = " + fmt2.format(rs) + " : corrélation " +
        forceCorrelation(rs) + (rs > 0 ? ", positive" : rs < 0 ? ", négative" : "") + " (" + pts.length + " points).";
  }

  function majCorrelations(zone) {
    $("niv-dep").setAttribute("aria-selected", etat.niveau === "dep");
    $("niv-com").setAttribute("aria-selected", etat.niveau === "com");
    var pts = pointsCorrelation(zone);
    var n = nbAnnees();
    var aide = (etat.niveau === "dep" ? "Les " + pts.length + " départements métropolitains" +
      (zone.type === "FR" ? "" : ", ceux de la zone choisie en orange") + ". " :
      "Communes de plus de 10 000 habitants" + (zone.type === "FR" ? "" : " de la zone choisie") + ". ") +
      "Accidents : moyenne par an sur " + (n > 1 ? n + " ans (" + etat.debut + "–" + etat.fin + ")" : etat.debut) +
      ". Population et km d'aménagements : valeurs actuelles.";
    if (pts.length < 10) {
      aide += " Trop peu de points (" + pts.length + ") pour calculer une corrélation fiable : choisissez une zone plus large.";
    }
    $("aide-correl").textContent = aide;
    if (window.Chart) {
      nuage("g-c1", "coef-1", pts, function (p) { return p.km; }, function (p) { return p.acc; },
        "Km d'aménagements cyclables", "Accidents par an");
      nuage("g-c2", "coef-2", pts, function (p) { return p.pop; }, function (p) { return p.acc; },
        "Habitants", "Accidents par an");
      nuage("g-c3", "coef-3", pts, function (p) { return p.km / p.pop * 1e4; }, function (p) { return p.acc / p.pop * 1e5; },
        "Km pour 10 000 habitants", "Accidents pour 100 000 hab. par an");
    }
    $("d-correl").innerHTML = tableHTML(
      ["Zone", "Accidents par an", "Population", "Km d'aménagements", "Km pour 10 000 hab.", "Accidents pour 100 000 hab. par an"],
      pts.map(function (p) {
        return [p.nom, fmt1.format(p.acc), p.pop, p.km, fmt1.format(p.km / p.pop * 1e4), fmt1.format(p.acc / p.pop * 1e5)];
      }));
  }

  // ---------------------------------------------------------------- démarrage

  charger("data/accidents/national.json").then(function (nat) {
    etat.nat = nat;
    etat.annees = nat.annees;
    zonesDe("R").forEach(function (r) { option($("f-region"), r.code, r.nom); });
    remplirAnnees();
    lireAdresse();
    if (nat.source_texte) $("source-acc").textContent = nat.source_texte;

    $("f-region").addEventListener("change", function (e) {
      etat.region = e.target.value; etat.dep = ""; etat.ville = ""; etat.arr = ""; rendre();
    });
    $("f-dep").addEventListener("change", function (e) {
      etat.dep = e.target.value; etat.ville = ""; etat.arr = "";
      if (etat.dep) etat.region = (etat.nat.zones_info["D" + etat.dep].parent || "").slice(1);
      rendre();
    });
    recherche = RechercheVille.attacher($("f-ville"), $("f-ville-suggestions"), function (v) {
      etat.ville = v.entiere || v.code;
      etat.arr = v.entiere ? v.code : "";
      etat.dep = depDeCommune(etat.ville);
      var zi = etat.nat.zones_info["D" + etat.dep];
      if (!zi) { etat.ville = ""; etat.arr = ""; etat.dep = ""; }
      else etat.region = (zi.parent || "").slice(1);
      rendre();
    });
    $("f-ville").addEventListener("search", function () {     // bouton « effacer » du champ
      if (!$("f-ville").value && etat.ville) { etat.ville = ""; etat.arr = ""; rendre(); }
    });
    $("f-arr").addEventListener("change", function (e) { etat.arr = e.target.value; rendre(); });
    $("f-debut").addEventListener("change", function (e) {
      etat.debut = parseInt(e.target.value, 10); if (etat.debut > etat.fin) etat.fin = etat.debut; rendre();
    });
    $("f-fin").addEventListener("change", function (e) {
      etat.fin = parseInt(e.target.value, 10); if (etat.fin < etat.debut) etat.debut = etat.fin; rendre();
    });
    $("niv-dep").addEventListener("click", function () { etat.niveau = "dep"; majCorrelations(etat.zone); });
    $("niv-com").addEventListener("click", function () { etat.niveau = "com"; majCorrelations(etat.zone); });
    return rendre();
  }).catch(function (e) {
    if (window.console) console.error(e);
    $("sous-titre").textContent = "";
    $("alertes").innerHTML = '<div class="alerte" role="alert"><strong>Données indisponibles</strong>' +
      "Les statistiques d'accidents n'ont pas pu être chargées. Elles sont recalculées chaque jour : réessayez plus tard.</div>";
  });
})();
