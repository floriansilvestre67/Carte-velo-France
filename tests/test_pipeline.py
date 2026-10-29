"""Tests de bout en bout du script de données, sur le monde fictif de conftest.py."""

import json

import pytest
from conftest import CODES, bnac, ligne

import construire_donnees
import indicateurs
from reseau import ClientFichiers
from sources import amenagements, vls


def lancer(monde, sortie_nom="site", urls=None, precedent=None):
    sortie = monde["dossier"] / sortie_nom
    client = ClientFichiers(urls or monde["urls"])
    meta = construire_donnees.construire(client, sortie, monde["dossier"] / "travail", precedent)
    geo = json.loads((sortie / "departements.geojson").read_text(encoding="utf-8"))
    stations = json.loads((sortie / "stations.json").read_text(encoding="utf-8"))
    props = {f["properties"]["code"]: f["properties"] for f in geo["features"]}
    return meta, props, stations, sortie


def L(code, dy=0.0):
    return amenagements.longueur_km({"type": "LineString", "coordinates": ligne(code, dy=dy)})


# ---------------------------------------------------------------- unités

def test_categories_bnac():
    assert amenagements.categorie("PISTE CYCLABLE") == "pistes"
    assert amenagements.categorie(" piste  cyclable ") == "pistes"
    assert amenagements.categorie("BANDE CYCLABLE") == "bandes"
    assert amenagements.categorie("VOIE VERTE") == "voies_vertes"
    assert amenagements.categorie("DOUBLE SENS CYCLABLE PISTE") == "double_sens"
    assert amenagements.categorie("COULOIR BUS+VELO") == "autres"
    assert amenagements.categorie("Aménagement mixte piéton vélo hors voie verte") == "autres"
    assert amenagements.categorie("AUCUN") is None
    assert amenagements.categorie(None) is None


def test_longueur_geodesique():
    # 1° de longitude à l'équateur ≈ 111,32 km
    km = amenagements.longueur_km({"type": "LineString", "coordinates": [[0, 0], [1, 0]]})
    assert km == pytest.approx(111.32, abs=0.01)


def test_ressource_la_plus_recente(monde):
    r = amenagements.trouver_ressource(ClientFichiers(monde["urls"]))
    assert r["title"] == "france-20261001.geojson"


def test_decouverte_gbfs_toutes_versions():
    v1 = {"data": {"en": {"feeds": [{"name": "free_bike_status", "url": "u1"}]}}}
    v2 = {"data": {"en": {"feeds": [{"name": "a", "url": "en"}]}, "fr": {"feeds": [{"name": "a", "url": "fr"}]}}}
    v3 = {"data": {"feeds": [{"name": "vehicle_status", "url": "u3"}]}}
    assert vls.lire_decouverte(v1) == {"free_bike_status": "u1"}
    assert vls.lire_decouverte(v2) == {"a": "fr"}  # le français est préféré
    assert vls.lire_decouverte(v3) == {"vehicle_status": "u3"}


def test_rangs_centiles_et_egalites():
    r = indicateurs.rangs_centiles({"a": 1, "b": 2, "c": 2, "d": 3, "e": None})
    assert r == {"a": 0.0, "b": 50.0, "c": 50.0, "d": 100.0, "e": None}
    assert indicateurs.rangs_nationaux({"a": 1, "b": 2, "c": 2, "d": None}) == {"a": 3, "b": 1, "c": 1, "d": None}


# ---------------------------------------------------------------- bout en bout

def test_amenagements(monde):
    meta, props, _, _ = lancer(monde)
    p63 = props["63"]
    assert p63["km_pistes"] == pytest.approx(L("63"), abs=0.01)
    assert p63["km_bandes"] == pytest.approx(2 * L("63", 0.01), abs=0.01)          # deux côtés
    assert p63["km_voies_vertes"] == pytest.approx(L("63", 0.02), abs=0.01)        # une seule fois
    assert props["69"]["km_double_sens"] == pytest.approx(L("69"), abs=0.01)       # localisé par position
    assert props["75"]["km_autres"] == pytest.approx(L("75") + L("75", 0.01), abs=0.01)  # MultiLineString
    assert props["2A"]["km_pistes"] == pytest.approx(L("2A"), abs=0.01)            # repli préfixe
    assert props["01"]["km_total"] == 0                                             # 97411 ignoré
    total = sum(p63[f"km_{c}"] for c in amenagements.CATEGORIES)
    assert p63["km_total"] == pytest.approx(total, abs=0.02)
    assert meta["sources"]["amenagements"]["statut"] == "ok"
    assert meta["sources"]["amenagements"]["date_donnees"] == "2026-10-01"
    types = meta["sources"]["amenagements"]["km_par_type"]
    assert set(types) == {"PISTE CYCLABLE", "BANDE CYCLABLE", "VOIE VERTE",
                          "DOUBLE SENS CYCLABLE NON MATERIALISE", "COULOIR BUS+VELO"}


def test_vls(monde):
    meta, props, stations, _ = lancer(monde)
    assert (props["63"]["vls_stations"], props["63"]["vls_velos"]) == (2, 10)
    assert (props["75"]["vls_stations"], props["75"]["vls_velos"]) == (1, 6)   # 4 vélos + 1 cargo + 1 libre
    assert (props["69"]["vls_stations"], props["69"]["vls_velos"]) == (0, 5)
    assert props["01"]["vls_stations"] == 0
    assert (props["33"]["vls_stations"], props["33"]["vls_velos"]) == (1, 2)   # flux séparés assemblés
    assert (props["44"]["vls_stations"], props["44"]["vls_velos"]) == (1, 4)   # vehicle_types en panne
    assert len(stations["stations"]) == 5
    noms = {s[2] for s in stations["stations"]}
    assert noms == {"Jaude", "Gare", "Châtelet", "Quinconces", "Commerce"}
    assert stations["systemes"].count("Vélo Fictif A") == 1                   # doublon écarté
    detail = meta["sources"]["vls"]["detail"]
    assert detail == "5 systèmes lus (8 jeux de données ; 1 sans vélo écartés, 1 doublons, 1 en échec)"


def test_indicateurs_et_score(monde):
    _, props, _, _ = lancer(monde)
    p = props["63"]
    assert p["population"] == sum(1000 * (CODES.index("63") + 1) + k for k in range(1, 13))
    assert p["surface_km2"] == pytest.approx(12 * 25 + 1, abs=0.1)
    assert p["km_10k_hab"] == pytest.approx(p["km_total"] / p["population"] * 1e4, rel=1e-2)
    assert p["vls_stations_100k"] == pytest.approx(2 / p["population"] * 1e5, rel=1e-2)
    for q in props.values():
        assert 0 <= q["score"] <= 100
        assert q["score_nb_indicateurs"] == 6
        assert q["rangs"]["score"] >= 1
    meilleur = min(props.values(), key=lambda q: q["rangs"]["score"])
    assert meilleur["code"] in ("63", "75")


def test_source_en_panne_sans_precedent(monde):
    urls = dict(monde["urls"])
    urls[vls.URL_API_JEUX] = None
    meta, props, stations, _ = lancer(monde, urls=urls)
    assert meta["sources"]["vls"]["statut"] == "indisponible"
    assert props["63"]["vls_stations"] is None and props["63"]["vls_stations_100k"] is None
    assert props["63"]["km_total"] > 0
    assert props["63"]["score_nb_indicateurs"] == 3   # score calculé sur les seuls aménagements
    assert stations["stations"] == []


def test_source_en_panne_reprise_du_precedent(monde):
    _, avant, _, sortie = lancer(monde, "v1")
    base = "https://site.example/"
    urls = dict(monde["urls"])
    for nom in ("departements.geojson", "meta.json", "stations.json"):
        urls[base + "data/" + nom] = sortie / nom
    urls[amenagements.URL_API_JEU] = None
    meta, apres, stations, _ = lancer(monde, "v2", urls=urls, precedent=base)
    src = meta["sources"]["amenagements"]
    assert src["statut"] == "reprise" and src["date_donnees"] == "2026-10-01"
    assert apres["63"]["km_total"] == avant["63"]["km_total"]
    assert apres["63"]["vls_stations"] == 2


def test_contours_indispensables(monde):
    urls = dict(monde["urls"])
    urls[next(u for u in urls if "france-geojson" in u)] = None
    with pytest.raises(Exception):
        lancer(monde, urls=urls)


def test_fichiers_legers(monde):
    _, _, _, sortie = lancer(monde)
    for f in sortie.iterdir():
        assert f.stat().st_size < 50 * 1024 * 1024


def test_bnac_fixture_complete():
    assert len(bnac()["features"]) == 10


def test_regions(monde):
    meta, props, _, _ = lancer(monde)
    assert props["63"]["region"] == "84" and props["63"]["region_nom"] == "Auvergne-Rhône-Alpes"
    assert all(p["region"] for p in props.values())
    assert meta["sources"]["regions"]["statut"] == "ok"


def test_regions_indisponibles(monde):
    from sources import regions
    urls = dict(monde["urls"])
    urls[regions.URL_REGIONS] = None
    meta, props, _, _ = lancer(monde, urls=urls)
    assert meta["sources"]["regions"]["statut"] == "indisponible"
    assert props["63"]["region"] is None
    assert props["63"]["score"] is not None   # le reste n'est pas affecté


def test_classement_communes(monde):
    _, _, _, sortie = lancer(monde)
    c = json.loads((sortie / "classement-communes.json").read_text(encoding="utf-8"))
    lignes = [dict(zip(c["champs"], l)) for l in c["lignes"]]
    assert c["seuil_population"] == 10_000
    assert all(l["pop"] >= 10_000 for l in lignes)
    paris = next(l for l in lignes if l["code"] == "75056")
    assert paris["nom"] == "Paris" and paris["dep"] == "75"
    scores = [l["score"] for l in lignes if l["score"] is not None]
    assert scores and all(0 <= s <= 100 for s in scores)
    l63 = next(l for l in lignes if l["code"] == "63012")
    assert l63["km_10k_hab"] == pytest.approx(l63["km_total"] / l63["pop"] * 1e4, rel=1e-3)


def test_score_simple(monde):
    meta, props, _, sortie = lancer(monde)
    # Départements : deux ratios, rangs centiles, rang avec ex æquo ; le score complet ne change pas
    for p in props.values():
        assert "score" in p and p["score_simple"] is None or 0 <= p["score_simple"] <= 100
    classes = [p for p in props.values() if p["score_simple"] is not None]
    meilleur = min(classes, key=lambda p: p["rang_score_simple"])
    assert meilleur["rang_score_simple"] == 1
    assert meilleur["score_simple"] == max(p["score_simple"] for p in classes)
    assert all(p["nb_classes_score_simple"] == len(classes) for p in props.values())
    # Communes : score, rang, ex æquo dans les fiches ; commune sans population non classée
    f63 = json.loads((sortie / "communes" / "63.json").read_text(encoding="utf-8"))
    sur = f63["score_simple"]["sur"]
    c = f63["communes"]
    assert "ss" not in c["99999"]
    notes = [v for v in c.values() if "ss" in v]
    assert notes and all(1 <= v["rs"] <= sur and 0 <= v["ss"] <= 100 and v["eq"] >= 1 for v in notes)
    # Le rang est cohérent avec le score : un meilleur score a un meilleur rang
    a, b = sorted(notes, key=lambda v: -v["ss"])[:2]
    assert a["rs"] <= b["rs"]


def test_rangs_rapides_et_plancher():
    assert indicateurs.rangs_rapides({"a": 3, "b": 5, "c": 3, "d": None}) == {"a": (2, 2), "b": (1, 1), "c": (2, 2), "d": None}
    # Hameau de 30 habitants avec 1 km : ramené à 2 000 habitants, il ne dépasse pas une ville bien équipée
    r = indicateurs.score_simple_communes({
        "hameau": {"p": 30, "km": {"t": 1}, "vls": {"st": 0}},
        "ville": {"p": 100_000, "km": {"t": 300}, "vls": {"st": 50}},
        "vide": {"p": 500, "km": {"t": 0}, "vls": {"st": 0}},
        "sans_donnee": {"p": 800, "km": None, "vls": {"st": 0}}})
    assert r["sur"] == 3 and "sans_donnee" not in r["communes"]
    assert r["communes"]["ville"][1] == 1 and r["communes"]["hameau"][1] == 2
