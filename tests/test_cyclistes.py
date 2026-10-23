"""Actifs allant travailler à vélo (Insee) : lecture du fichier et intégration aux données publiées."""

import json

import pytest
from conftest import CODES
from test_pipeline import lancer

from sources import cyclistes


def lire_publie(sortie, chemin):
    return json.loads((sortie / chemin).read_text(encoding="utf-8"))


def test_lecture_insee(monde):
    from sources import communes
    corr = communes.Correspondance(
        [{"code": f"{c}{k:03d}"} for c in CODES for k in range(1, 13)]
        + [{"code": "75056"}, {"code": "69123"}], {})
    res = cyclistes.lire(monde["urls"][cyclistes.URL_FICHIER], corr)
    assert res["annee"] == 2021
    c = res["communes"]
    assert c["63001"] == {"v": 1, "a": 400}               # 1,4 arrondi ; « 400,5 » à virgule décimale
    assert c["63012"]["v"] == 12
    assert c["75056"]["v"] == 70000                      # Paris : la commune entière, pas + 1er arr.
    assert c["69123"] == {"v": 3000, "a": 30000}         # Lyon : somme des arrondissements
    assert "00000" not in c and res["stats"]["inconnues"] >= 1
    par_dep = cyclistes.par_departement(c, corr)
    assert par_dep["63"] == sum(range(1, 13))


def test_cyclistes_publies(monde):
    meta, _, _, sortie = lancer(monde)
    src = meta["sources"]["cyclistes"]
    assert src["statut"] == "ok" and src["annee"] == 2021
    nat = lire_publie(sortie, "accidents/national.json")
    assert nat["cyclistes_annee"] == 2021
    assert nat["zones_info"]["D63"]["cyc"] == sum(range(1, 13))
    assert nat["zones_info"]["FR"]["cyc"] >= nat["zones_info"]["D63"]["cyc"]
    region = nat["zones_info"]["D63"]["parent"]
    assert nat["zones_info"][region]["cyc"] >= nat["zones_info"]["D63"]["cyc"]
    dep = lire_publie(sortie, "communes/63.json")
    assert dep["communes"]["63005"]["cyc"] == {"v": 5, "a": 400}


def test_cyclistes_en_panne(monde):
    # Sans version précédente : indisponible, et aucune valeur inventée
    urls = dict(monde["urls"])
    urls[cyclistes.URL_FICHIER] = None
    meta, _, _, sortie = lancer(monde, "v0", urls=urls)
    assert meta["sources"]["cyclistes"]["statut"] == "indisponible"
    nat = lire_publie(sortie, "accidents/national.json")
    assert nat["zones_info"]["D63"]["cyc"] is None and "cyclistes_annee" not in nat
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
    assert nat["zones_info"]["D63"]["cyc"] == sum(range(1, 13)) and nat["cyclistes_annee"] == 2021
    assert lire_publie(sortie2, "communes/63.json")["communes"]["63005"]["cyc"]["v"] == 5


def test_colonne_velo_absente(tmp_path):
    import zipfile
    chemin = tmp_path / "x.zip"
    with zipfile.ZipFile(chemin, "w") as z:
        z.writestr("a.csv", "CODGEO;P21_ACTOCC15P\n63001;10")
    with pytest.raises(ValueError):
        cyclistes.lire(chemin, None)
