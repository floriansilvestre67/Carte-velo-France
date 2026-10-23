"""Actifs allant travailler à vélo (Insee, 2017 et 2023) : lecture et intégration aux données publiées."""

import json
import zipfile

import pytest
from conftest import CODES
from test_pipeline import lancer

from sources import communes, cyclistes

DEP63_2017 = sum(k for k in range(1, 13)) + 0.4 * 12       # valeurs Insee décimales, arrondies au total
DEP63_2023 = sum(2 * k for k in range(1, 13)) + 0.4 * 12


def lire_publie(sortie, chemin):
    return json.loads((sortie / chemin).read_text(encoding="utf-8"))


def correspondance():
    return communes.Correspondance(
        [{"code": f"{c}{k:03d}"} for c in CODES for k in range(1, 13)] + [{"code": "75056"}, {"code": "69123"}], {})


def test_lecture_insee(monde):
    res = cyclistes.lire(monde["urls"][cyclistes.URL_FICHIER], correspondance())
    assert res["annees"] == [2017, 2023]                     # 2012 (vélo + deux-roues) écartée
    c = res["communes"]
    assert c["63001"] == {"2017": [1, 400], "2023": [2, 410]}
    assert c["63012"]["2023"][0] == 24
    assert c["75056"]["2023"] == [90000, 1000000]            # arrondissement 75101 non ajouté
    assert c["69123"]["2023"] == [None, None]                # « K » : inconnu, pas 0
    assert c["69123"]["2017"][0] == 18000
    assert "00000" not in c and res["stats"]["inconnues"] == 1
    assert res["zones"]["D63"] == {"2017": round(DEP63_2017), "2023": round(DEP63_2023)}
    assert res["zones"]["R84"] == {"2017": 1234, "2023": 2345}


def test_code_velo_lu_dans_les_metadonnees():
    meta = [{"COD_VAR": "TRANS", "COD_MOD": "3T4", "LIB_MOD": "Vélo ou deux-roues motorisé"},
            {"COD_VAR": "TRANS", "COD_MOD": "7", "LIB_MOD": "Vélo"}]
    assert cyclistes.code_velo(meta) == "7"
    with pytest.raises(ValueError):
        cyclistes.code_velo([{"COD_VAR": "TRANS", "COD_MOD": "5", "LIB_MOD": "Voiture"}])


def test_cyclistes_publies(monde):
    meta, _, _, sortie = lancer(monde)
    src = meta["sources"]["cyclistes"]
    assert src["statut"] == "ok" and src["annees"] == [2017, 2023]
    nat = lire_publie(sortie, "accidents/national.json")
    assert nat["cyclistes_annees"] == [2017, 2023]
    zi = nat["zones_info"]
    assert zi["D63"]["cyc"] == {"2017": round(DEP63_2017), "2023": round(DEP63_2023)}
    assert zi["FR"]["cyc"]["2023"] == sum(round(sum(2 * k + 0.4 for k in range(1, 13))) for _ in CODES)
    region = zi["D63"]["parent"]
    assert zi[region]["cyc"]["2023"] is not None
    dep = lire_publie(sortie, "communes/63.json")
    assert dep["communes"]["63005"]["cyc"] == {"2017": [5, 400], "2023": [10, 410]}


def test_cyclistes_en_panne(monde):
    # Sans version précédente : indisponible, et aucune valeur inventée
    urls = dict(monde["urls"])
    urls[cyclistes.URL_FICHIER] = None
    meta, _, _, sortie = lancer(monde, "v0", urls=urls)
    assert meta["sources"]["cyclistes"]["statut"] == "indisponible"
    nat = lire_publie(sortie, "accidents/national.json")
    assert nat["zones_info"]["D63"]["cyc"] is None and "cyclistes_annees" not in nat
    assert "cyc" not in lire_publie(sortie, "communes/63.json")["communes"]["63005"]


def test_cyclistes_reprise(monde):
    _, _, _, sortie = lancer(monde, "v1")
    base = "https://site.example/"
    urls = dict(monde["urls"])
    for nom in ("departements.geojson", "meta.json", "stations.json", "accidents/national.json",
                "communes/63.json"):
        urls[base + "data/" + nom] = sortie / nom
    urls[cyclistes.URL_FICHIER] = None
    meta, _, _, sortie2 = lancer(monde, "v2", urls=urls, precedent=base)
    assert meta["sources"]["cyclistes"]["statut"] == "reprise"
    nat = lire_publie(sortie2, "accidents/national.json")
    assert nat["zones_info"]["D63"]["cyc"]["2023"] == round(DEP63_2023)
    assert nat["cyclistes_annees"] == [2017, 2023]
    assert lire_publie(sortie2, "communes/63.json")["communes"]["63005"]["cyc"]["2023"] == [10, 410]


def test_ancien_format_non_repris():
    assert not cyclistes.format_valide({"v": 5, "a": 400})
    assert cyclistes.format_valide({"2017": [5, 400]})


def test_fichiers_manquants(tmp_path):
    chemin = tmp_path / "x.zip"
    with zipfile.ZipFile(chemin, "w") as z:
        z.writestr("a.csv", "GEO;OBS_VALUE\n63001;10")
    with pytest.raises(ValueError):
        cyclistes.lire(chemin, None)
