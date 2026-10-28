"""Tests des points d'intérêt (DATAtourisme, Mérimée, Muséofile)."""

import json

import pytest
from test_pipeline import lancer

from sources import poi


@pytest.fixture
def res(monde):
    meta, props, _, sortie = lancer(monde)
    return meta, sortie


def points(sortie, dep):
    f = json.loads((sortie / "poi" / f"{dep}.json").read_text(encoding="utf-8"))
    return f, [dict(zip(f["champs"], p)) for p in f["points"]]


def test_classes_et_categories():
    assert poi.classes("https://x/core#Museum|http://schema.org/Museum") == {"museum"}
    assert poi.categorie_datatourisme({"culturalsite", "library"}, "Médiathèque") is None
    assert poi.categorie_datatourisme({"equipmentrental"}, "Location de vélos") == poi.C_SERVICE
    assert poi.categorie_datatourisme({"equipmentrental"}, "Location de kayaks") is None
    assert poi.categorie_datatourisme({"cyclingtour", "tour"}, "Boucle") == poi.C_ITINERAIRE
    assert poi.coordonnees("48.39, 4.52") == (48.39, 4.52)
    assert poi.coordonnees("") is None


def test_selection_et_dedoublonnage(res):
    meta, sortie = res
    f, pts = points(sortie, "63")
    noms = {p["nom"]: p for p in pts}
    cat = lambda p: f["categories"][p["categorie"]]  # noqa: E731
    assert "Hôtel du Centre" not in noms and "Médiathèque" not in noms and "Location de kayaks" not in noms
    assert "Sentier pédestre" not in noms
    assert cat(noms["Boucle des volcans à vélo"]) == "Itinéraire vélo"
    assert cat(noms["Location de vélos du lac"]) == "Location ou réparation de vélos"
    assert cat(noms["Jardin Lecoq"]) == "Parc ou jardin" and cat(noms["Plage du lac"]) == "Nature et point de vue"
    # Église : DATAtourisme + Mérimée à 11 m -> un seul lieu, devenu monument historique classé
    eglises = [p for p in pts if p["nom"] == "Église Notre-Dame"]
    assert len(eglises) == 1 and cat(eglises[0]) == "Monument historique" and eglises[0]["statut"] == "classé MH"
    # Musée : DATAtourisme + Muséofile (noms proches, 70 m) -> un seul, statut musée de France
    musees = [p for p in pts if cat(p) == "Musée"]
    assert len(musees) == 1 and musees[0]["statut"] == "musée de France"
    assert noms["Jardin Lecoq"]["commune"].startswith("63")
    assert "Sans coordonnées" not in noms
    _, pts69 = points(sortie, "69")
    assert pts69[0]["nom"] == "Musée des Confluences" and pts69[0]["source"] == 2
    m = meta["sources"]["poi"]
    assert m["statut"] == "ok" and "3 doublons fusionnés" in m["detail"] and "dont 6 monuments" in m["detail"]
    assert "museum" in m["classes_gardees"] and "hotel" in m["classes_ecartees"]


def test_lieux_les_plus_remarquables(res):
    meta, sortie = res
    f, pts = points(sortie, "63")
    noms = {p["nom"]: p for p in pts}
    # Monument peu connu sur Wikidata (2 pages < seuil) : écarté ; l'église (12 pages) reste
    assert "Halle aux blés" not in noms and "Église Notre-Dame" in noms
    # Patrimoine non protégé, musée sans label, parc sans label, nature sans description : écartés
    for nom in ("Lavoir", "Petit musée", "Square Martin", "Mare du bois"):
        assert nom not in noms
    # Jardin remarquable : fusionné avec la fiche DATAtourisme (description gardée), et jardin seul ajouté
    assert noms["Jardin Lecoq"]["statut"] == "jardin remarquable" and len(noms["Jardin Lecoq"]["description"]) > 80
    assert noms["Jardin de la Source"]["source"] == f["sources"].index("Jardins remarquables")
    diag = meta["sources"]["poi"]["diagnostic"]
    assert diag["wikidata_references"] == 2 and diag["monuments_par_seuil"]["5"] == 1


def test_repli_sans_wikidata():
    lieux = [{"cat": poi.C_MH, "statut": "classé MH", "src": "DATAtourisme", "desc": "x" * 90, "lien": ""},
             {"cat": poi.C_MH, "statut": "classé MH", "src": "Mérimée", "desc": "12e s.", "lien": ""},
             {"cat": poi.C_MH, "statut": "inscrit MH", "src": "DATAtourisme", "desc": "x" * 90, "lien": ""}]
    from collections import Counter
    assert len(poi.selectionner(lieux, None, Counter())) == 1
    assert poi.reference_merimee({"lien": "", "autre_lien": "https://pop.culture.gouv.fr/notice/merimee/PA00088801"}) == "PA00088801"


def test_recalcul_hebdomadaire_et_reprise(monde, monkeypatch):
    _, _, _, s1 = lancer(monde, "v1")
    base = "https://site.example/"
    urls = dict(monde["urls"])
    for f in s1.rglob("*"):
        if f.is_file():
            urls[base + "data/" + f.relative_to(s1).as_posix()] = f
    urls[poi.URL_API.format(poi.ID_DATATOURISME)] = None        # DATAtourisme en panne
    meta, _, _, s2 = lancer(monde, "v2", urls=urls, precedent=base)
    assert meta["sources"]["poi"]["statut"] == "ok"             # moins de 7 jours : fichiers repris tels quels
    assert (s2 / "poi" / "63.json").read_text() == (s1 / "poi" / "63.json").read_text()
    monkeypatch.setenv("FORCER_POI", "1")
    meta, _, _, s3 = lancer(monde, "v3", urls=urls, precedent=base)
    assert meta["sources"]["poi"]["statut"] == "reprise"        # recalcul forcé mais source en panne
    assert (s3 / "poi" / "63.json").exists()
