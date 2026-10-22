"""Tests de la livraison « ville » : contours, index de recherche, VLS par commune."""

import json

import pytest
from conftest import centre
from test_pipeline import lancer

from sources import contours_communes


@pytest.fixture
def sortie(monde):
    meta, props, _, sortie = lancer(monde)
    return meta, sortie


def lire(sortie, chemin):
    return json.loads((sortie / chemin).read_text(encoding="utf-8"))


def test_contours_par_departement(sortie):
    meta, s = sortie
    c63 = lire(s, "contours/63.geojson")
    assert len(c63["features"]) == 12
    assert {f["properties"]["code"] for f in c63["features"]} >= {"63001", "63012"}
    c75 = lire(s, "contours/75.geojson")
    assert [f["properties"]["code"] for f in c75["features"]] == ["75056"]   # arrondissements fusionnés
    diag = meta["sources"]["contours_communes"]["diagnostic"]
    assert diag["arrondissements"] == 2 and diag["paris_entier"] is True
    assert "code" in diag["cles_proprietes"]
    # coordonnées arrondies à 4 décimales
    x = c63["features"][0]["geometry"]["coordinates"][0][0][0]
    assert round(x, 4) == x


def test_index_recherche(sortie):
    _, s = sortie
    index = lire(s, "communes-index.json")
    lignes = {l[0]: l for l in index["communes"]}
    assert lignes["63001"][1] == "Commune 63-1" and lignes["63001"][2] == "63001"
    assert lignes["75101"][4] == "75056"          # arrondissement rattaché à Paris
    assert lignes["69383"][4] == "69123"
    assert "97411" not in lignes                   # outre-mer exclu
    pops = [l[3] for l in index["communes"]]
    assert pops == sorted(pops, reverse=True)     # les plus peuplées d'abord


def test_vls_par_commune(sortie):
    _, s = sortie
    c63 = lire(s, "communes/63.json")["communes"]
    assert sum(v["vls"]["st"] for v in c63.values()) == 2
    assert sum(v["vls"]["v"] for v in c63.values()) == 10
    paris = lire(s, "communes/75.json")["communes"]["75056"]["vls"]
    assert paris == {"st": 0, "zv": 1, "v": 6}     # station virtuelle (free-floating) comptée à part
    stations = lire(s, "stations.json")["stations"]
    assert any(st[5] == 1 for st in stations)


def test_localisateur_commune(sortie):
    _, s = sortie
    feats = {"63": lire(s, "contours/63.geojson")["features"]}
    loc = contours_communes.LocalisateurCommune(feats)
    lon, lat = centre("63")
    assert loc.trouver(lon, lat) is not None
    assert loc.trouver(50, 50) is None


def test_contours_indisponibles(monde):
    urls = dict(monde["urls"])
    urls[contours_communes.URL_CONTOURS] = None
    meta, props, _, s = lancer(monde, urls=urls)
    assert meta["sources"]["contours_communes"]["statut"] == "indisponible"
    assert not (s / "contours").exists()
    assert "vls" not in lire(s, "communes/63.json")["communes"]["63001"]
    assert props["63"]["vls_stations"] == 2       # le niveau département ne change pas
