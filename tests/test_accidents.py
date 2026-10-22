"""Tests des accidents de vélo et des fichiers par commune, sur le monde fictif de conftest.py."""

import json

import pytest
from conftest import ligne
from test_pipeline import lancer

from sources import accidents, amenagements
from sources.accidents import G_GRAVE, G_INDEMNE, G_MORTEL, G_NR
from sources.communes import Correspondance, commune_entiere


def L(code, dy=0.0):
    return amenagements.longueur_km({"type": "LineString", "coordinates": ligne(code, dy=dy)})


# ---------------------------------------------------------------- unités

def test_normaliser_lieu():
    assert accidents.normaliser_lieu("75", "75012") == ("75", "75112")   # Paris avant 2010
    assert accidents.normaliser_lieu("75", "75112") == ("75", "75112")
    assert accidents.normaliser_lieu("1", "01005") == ("01", "01005")    # zéro initial manquant
    assert accidents.normaliser_lieu("1", "1005") == ("01", "01005")
    assert accidents.normaliser_lieu("2A", "2A004") == ("2A", "2A004")
    assert accidents.normaliser_lieu("971", "97101") == ("971", "97101")
    assert accidents.normaliser_lieu("5", None) == ("05", None)
    assert accidents.normaliser_lieu("75", "75056") == ("75", "75056")   # commune entière, pas un arrondissement


def test_commune_entiere():
    assert commune_entiere("75108") == "75056"
    assert commune_entiere("69383") == "69123"
    assert commune_entiere("13205") == "13055"
    assert commune_entiere("13001") == "13001"   # Aix-en-Provence, pas un arrondissement
    assert commune_entiere("75056") == "75056"


def test_correspondance_anciennes_communes():
    c = Correspondance([{"code": "63001", "codeDepartement": "63"}, {"code": "75056", "codeDepartement": "75"}],
                       {"63999": "63001"})
    assert c.resoudre("63999") == "63001"
    assert c.resoudre("75115") == "75056"
    assert c.resoudre("12345") is None
    assert c.departement("12345") == "12"


def test_groupes_vehicules():
    assert accidents.groupes_vehicules("7 / 18") == [0, 3]
    assert accidents.groupes_vehicules("80") == [5]
    assert accidents.groupes_vehicules(None) == []
    assert accidents.groupes_vehicules("999") == [accidents.V_AUTRE]


# ---------------------------------------------------------------- bout en bout

@pytest.fixture
def resultat(monde):
    meta, props, _, sortie = lancer(monde)
    national = json.loads((sortie / "accidents" / "national.json").read_text(encoding="utf-8"))
    fichiers = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in (sortie / "communes").glob("*.json")}
    return meta, props, national, fichiers


def acc(fichiers, dep):
    champs = fichiers[dep]["accidents"]["champs"]
    return [dict(zip(champs, l)) for l in fichiers[dep]["accidents"]["lignes"]]


def test_accidents_regroupes(resultat):
    meta, _, national, fichiers = resultat
    assert meta["sources"]["accidents"]["statut"] == "ok"
    assert national["annees"] == list(range(2010, 2024))
    fr = national["zones"]["FR"]
    assert sum(fr["acc"]) == 6                     # 7 Num_Acc distincts, dont 1 outre-mer écarté
    assert sum(fr["tues"]) == 1 and sum(fr["legers"]) == 3 and sum(fr["hosp"]) == 1
    assert sum(fr["indemnes"]) == 1 and sum(fr["nr"]) == 1

    a = next(x for x in acc(fichiers, "63") if x["an"] == 2021)
    assert a["gravite"] == G_MORTEL and a["tues"] == 1 and a["legers"] == 1
    assert a["vehicule"] == 3                       # bus plus « lourd » que la voiture
    assert a["trajet"] == 4                         # motif du cycliste tué : promenade
    assert a["situ"] == 1                           # piste cyclable

    b = acc(fichiers, "75")[0]
    assert b["com"] == "75056" and b["arr"] == "75112"          # commune entière + arrondissement
    assert b["vehicule"] == accidents.V_PIETON and b["gravite"] == G_GRAVE

    c = acc(fichiers, "01")[0]
    assert c["gravite"] == G_INDEMNE and c["trajet"] == 6 and c["situ"] == 7 and c["vehicule"] == 5

    e = next(x for x in acc(fichiers, "63") if x["an"] == 2015)
    assert e["com"] == "63001" and e["arr"] == ""              # ancienne commune rattachée
    assert e["gravite"] == G_NR and e["vehicule"] == 2 and e["situ"] == 5
    assert "971" not in fichiers


def test_zones_et_regions(resultat):
    _, props, national, _ = resultat
    z = national["zones"]
    i2021 = national["annees"].index(2021)
    assert z["D63"]["acc"][i2021] == 1 and z["D2A"]["acc"][i2021] == 1
    assert sum(z["R84"]["acc"]) == 4                # 63 (x2), 69 et 01 sont dans la région 84
    assert z["FR"]["veh"][i2021][3][G_MORTEL] == 1
    assert national["zones_info"]["D63"]["pop"] == props["63"]["population"]
    assert national["zones_info"]["D63"]["parent"] == "R84"
    assert national["zones_info"]["FR"]["km"] == pytest.approx(sum(p["km_total"] for p in props.values()), abs=0.1)
    assert national["libelles"]["vehicule"][3] == "Bus, car, tram ou train"
    assert national["ruptures"]


def test_communes_km_et_grandes_communes(resultat):
    _, _, national, fichiers = resultat
    c63 = fichiers["63"]["communes"]
    assert c63["63001"]["n"] == "Commune 63-1"
    assert c63["63002"]["km"]["bandes"] == pytest.approx(2 * L("63", 0.01), abs=0.01)
    assert c63["63005"]["km"] == {"t": 0}           # aucune piste : 0 et non « indisponible »
    assert fichiers["75"]["communes"]["75056"]["km"]["pistes"] == pytest.approx(L("75", 0.02), abs=0.01)
    g = national["grandes_communes"]
    i2021, i2015 = national["annees"].index(2021), national["annees"].index(2015)
    assert g["63001"]["acc"][i2021] == 1 and g["63001"]["acc"][i2015] == 1   # dont l'ancienne commune
    assert g["75056"]["acc"][national["annees"].index(2010)] == 1             # arrondissement regroupé
    assert g["69123"]["acc"][national["annees"].index(2023)] == 1
    assert all(v["p"] >= 10_000 for v in g.values())


def test_accidents_indisponibles(monde):
    urls = dict(monde["urls"])
    urls[accidents.URL_LIGNES] = None
    meta, props, _, sortie = lancer(monde, urls=urls)
    assert meta["sources"]["accidents"]["statut"] == "indisponible"
    assert not (sortie / "accidents" / "national.json").exists()
    f = json.loads((sortie / "communes" / "63.json").read_text(encoding="utf-8"))
    assert f["accidents"]["lignes"] == [] and f["communes"]["63001"]["n"]
    assert props["63"]["score"] is not None


def test_accidents_reprise(monde):
    _, _, _, sortie = lancer(monde, "v1")
    base = "https://site.example/"
    urls = dict(monde["urls"])
    for f in sortie.rglob("*.json"):
        urls[base + "data/" + f.relative_to(sortie).as_posix()] = f
    for f in sortie.glob("*.geojson"):
        urls[base + "data/" + f.name] = f
    urls[accidents.URL_LIGNES] = None
    meta, _, _, sortie2 = lancer(monde, "v2", urls=urls, precedent=base)
    assert meta["sources"]["accidents"]["statut"] == "reprise"
    f = json.loads((sortie2 / "communes" / "63.json").read_text(encoding="utf-8"))
    assert len(f["accidents"]["lignes"]) == 2
    nat = json.loads((sortie2 / "accidents" / "national.json").read_text(encoding="utf-8"))
    assert sum(nat["zones"]["FR"]["acc"]) == 6


def test_lecture_incomplete_detectee(monde):
    urls = dict(monde["urls"])
    from conftest import KOUMOUL_PAGE2
    urls[KOUMOUL_PAGE2] = None   # 2e page injoignable : on ne publie pas une série tronquée
    meta, _, _, _ = lancer(monde, urls=urls)
    assert meta["sources"]["accidents"]["statut"] == "indisponible"
