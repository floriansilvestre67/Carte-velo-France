"""Tests du stationnement vélo (indicateurs Ecolab et emplacements OSM)."""

import json

import pytest
from test_pipeline import lancer


@pytest.fixture
def res(monde):
    meta, props, _, sortie = lancer(monde)
    lire = lambda c: json.loads((sortie / c).read_text(encoding="utf-8"))  # noqa: E731
    return meta, props, lire


def test_indicateurs_departement(res):
    meta, props, _ = res
    p = props["63"]
    assert p["stat_places"] == 900               # relevé 2025 uniquement (500 + 20 + 300 + 80)
    assert p["stat_places_secu"] == 520          # cadre + cadre et roue
    assert p["stat_secu_1000"] == pytest.approx(5.2)
    assert props["01"]["stat_places"] is None    # non renseigné : indisponible, pas 0
    assert meta["sources"]["stationnement"]["date_donnees"] == "2025-01-01"
    assert "stat_secu_1000" in [i["cle"] for i in meta["indicateurs"]]
    assert "stat_secu_1000" not in meta["score_indicateurs"]
    assert p["rangs"]["stat_places"] == 2          # derrière Paris (1 000 places)


def test_indicateurs_commune(res):
    _, _, lire = res
    c = lire("communes/63.json")["communes"]["63001"]["stat"]
    assert c == {"p": 50, "s": 40, "s1000": pytest.approx(0.65, abs=0.01)}
    paris = lire("communes/75.json")["communes"]["75056"]["stat"]
    assert paris["p"] == 1000 and paris["s"] == 1000   # arrondissement regroupé avec Paris


def test_emplacements(res):
    meta, _, lire = res
    f = lire("stationnement/63.json")
    assert len(f["points"]) == 3                  # dont un sans code commune, localisé par sa position
    pts = [dict(zip(f["champs"], p)) for p in f["points"]]
    v = f["valeurs"]
    assert v["accroche"][pts[0]["accroche"]] == "cadre et roue"
    assert pts[0]["capacite"] == 10 and pts[0]["gratuit"] == 1 and pts[0]["couverture"] == 0
    assert pts[1]["capacite"] is None
    assert "ferme" in v["protection"][pts[2]["protection"]]
    osm = meta["sources"]["stationnement_osm"]
    assert osm["statut"] == "ok" and "3 emplacements" in osm["detail"]
    assert osm["coherence"]["total_osm"] == 16 and osm["coherence"]["total_officiel"] == 1900


def test_stationnement_indisponible(monde):
    from sources import stationnement
    urls = dict(monde["urls"])
    urls[stationnement.URL_API.format(stationnement.ID_PLACES)] = None
    meta, props, _, sortie = lancer(monde, urls=urls)
    assert meta["sources"]["stationnement"]["statut"] == "indisponible"
    assert props["63"]["stat_places"] is None
    assert props["63"]["score"] is not None
    assert (sortie / "stationnement" / "63.json").exists()   # les emplacements restent disponibles
