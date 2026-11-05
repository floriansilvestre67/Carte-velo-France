/* Carte Vélo France — page d'accueil : choix d'une ville ou d'un département et des calques,
   puis ouverture de la carte (carte.html?ville=…|dep=…&calques=…). */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var choix = null;              // { ville: code } ou { dep: code }
  var departements = [];         // [{ code, nom }] : chargés au premier usage de la recherche

  // Liste des départements (pour les proposer dans la recherche), chargée une seule fois
  var promesseDeps = null;
  function chargerDepartements() {
    if (!promesseDeps) {
      promesseDeps = fetch("data/departements.geojson").then(function (r) {
        if (!r.ok) throw new Error("geo");
        return r.json();
      }).then(function (g) {
        departements = g.features.map(function (f) { return { code: f.properties.code, nom: f.properties.nom }; });
      }).catch(function () { promesseDeps = null; });
    }
    return promesseDeps;
  }

  var champ = $("recherche-ville"), aide = $("aide-choix");
  champ.addEventListener("focus", chargerDepartements);
  RechercheVille.attacher(champ, $("suggestions-ville"), function (v) {
    choix = v.type === "departement" ? { dep: v.code } : { ville: v.entiere || v.code };
    aide.hidden = true;
  }, { departements: function () { return departements; } });
  // Texte modifié après un choix : le choix ne vaut plus
  champ.addEventListener("input", function () { choix = null; aide.hidden = true; });

  $("choix-carte").addEventListener("submit", function (e) {
    e.preventDefault();
    if (champ.value.trim() && !choix) {
      aide.textContent = "Choisissez une ville ou un département dans la liste proposée.";
      aide.hidden = false;
      champ.focus();
      return;
    }
    var q = new URLSearchParams();
    if (choix && choix.ville) q.set("ville", choix.ville);
    if (choix && choix.dep) q.set("dep", choix.dep);
    var calques = Array.prototype.map.call(document.querySelectorAll('input[name="calque"]:checked'),
      function (c) { return c.value; });
    if (calques.length) q.set("calques", calques.join(","));
    var s = q.toString();
    location.href = "carte.html" + (s ? "?" + s.replace(/%2C/g, ",") : "");
  });
})();
