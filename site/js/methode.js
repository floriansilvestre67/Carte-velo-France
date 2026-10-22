/* Page « Sources et méthode » : affiche l'état de chaque source lors de la dernière mise à jour. */
(function () {
  "use strict";
  var NOMS = {
    contours: "Contours des départements",
    communes: "Population et surface",
    regions: "Régions",
    amenagements: "Aménagements cyclables",
    vls: "Vélos en libre-service",
    accidents: "Accidents de vélo"
  };
  // Même regroupement que scripts/sources/amenagements.py
  function categorie(t) {
    if (t.indexOf("DOUBLE SENS") === 0) return "Double-sens";
    if (t === "PISTE CYCLABLE") return "Pistes";
    if (t === "BANDE CYCLABLE") return "Bandes";
    if (t === "VOIE VERTE") return "Voies vertes";
    return "Autres";
  }

  var ETATS = { ok: "À jour", reprise: "Chiffres de la veille", indisponible: "Indisponible" };

  function cellule(texte, classe) {
    var td = document.createElement("td");
    td.textContent = texte;
    if (classe) td.className = classe;
    return td;
  }

  fetch("data/meta.json").then(function (r) {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }).then(function (meta) {
    var d = new Date(meta.genere_le);
    document.getElementById("genere").textContent = "Dernier calcul : " +
      d.toLocaleString("fr-FR", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }).replace(/^1 /, "1er ") + ".";
    var corps = document.getElementById("etat-sources");
    Object.keys(NOMS).forEach(function (cle) {
      var s = (meta.sources || {})[cle];
      if (!s) return;
      var tr = document.createElement("tr");
      var th = document.createElement("th");
      th.scope = "row";
      th.textContent = NOMS[cle];
      tr.appendChild(th);
      tr.appendChild(cellule(ETATS[s.statut] || s.statut, "statut " + s.statut));
      var detail = s.detail || "";
      if (s.date_donnees) detail += (detail ? ". " : "") + "Données du " +
        new Date(s.date_donnees + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }).replace(/^1 /, "1er ") + ".";
      tr.appendChild(cellule(detail));
      corps.appendChild(tr);
    });

    // Détail des kilomètres par valeur brute du schéma national
    var types = ((meta.sources || {}).amenagements || {}).km_par_type;
    var corpsTypes = document.getElementById("types-bruts");
    corpsTypes.innerHTML = "";
    if (!types) {
      corpsTypes.appendChild(document.createElement("tr")).appendChild(cellule("Détail indisponible."));
    } else {
      var fmt = new Intl.NumberFormat("fr-FR");
      Object.keys(types).forEach(function (t) {
        var tr = document.createElement("tr");
        tr.appendChild(cellule(t.charAt(0) + t.slice(1).toLowerCase()));
        tr.appendChild(cellule(categorie(t)));
        var km = cellule(fmt.format(types[t]));
        km.style.textAlign = "right";
        tr.appendChild(km);
        corpsTypes.appendChild(tr);
      });
    }
  }).catch(function () {
    document.getElementById("genere").textContent = "L'état des données n'a pas pu être chargé.";
  });
})();
