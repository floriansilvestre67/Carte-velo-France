"""Données fictives au format réel des sources, pour tester sans réseau.

Le « monde fictif » :
  - 96 départements métropolitains, chacun un carré de 0,5° (vrais codes, faux contours) ;
  - 12 communes par département (geo.api.gouv.fr, surface en hectares) ;
  - quelques tronçons BNAC aux cas particuliers connus ;
  - 5 systèmes GBFS : v1.0, v2.2, v3.0, un système de trottinettes, un flux en panne,
    plus un jeu d'autopartage à ignorer.
"""

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "scripts"))

from sources import amenagements, communes, departements, vls  # noqa: E402

CODES = [f"{i:02d}" for i in range(1, 96) if i != 20] + ["2A", "2B"]
TAILLE = 0.5  # degrés


def carre(code):
    """Coin sud-ouest (lon, lat) du carré du département."""
    i = CODES.index(code)
    return -4.0 + (i % 12) * TAILLE, 42.0 + (i // 12) * TAILLE


def centre(code, dx=0.0, dy=0.0):
    lon, lat = carre(code)
    return [round(lon + TAILLE / 2 + dx, 6), round(lat + TAILLE / 2 + dy, 6)]


def ligne(code, longueur_deg=0.01, dy=0.0):
    a = centre(code, dy=dy)
    return [a, [a[0] + longueur_deg, a[1]]]


def ecrire(dossier: Path, nom: str, contenu) -> Path:
    chemin = dossier / nom
    chemin.write_text(json.dumps(contenu, ensure_ascii=False), encoding="utf-8")
    return chemin


def contours():
    feats = []
    for code in CODES:
        lon, lat = carre(code)
        anneau = [[lon, lat], [lon + TAILLE, lat], [lon + TAILLE, lat + TAILLE], [lon, lat + TAILLE], [lon, lat]]
        feats.append({"type": "Feature", "properties": {"code": code, "nom": f"Département {code}"},
                      "geometry": {"type": "Polygon", "coordinates": [anneau]}})
    return {"type": "FeatureCollection", "features": feats}


def liste_communes():
    liste = []
    for n, code in enumerate(CODES):
        for k in range(1, 13):
            liste.append({"code": f"{code}{k:03d}", "codeDepartement": code,
                          "population": 1000 * (n + 1) + k, "surface": 2500.0})  # 25 km²
    liste.append({"code": "97411", "codeDepartement": "974", "population": 150000, "surface": 14000.0})
    liste.append({"code": "99999", "codeDepartement": "63", "surface": 100.0})  # sans population
    return liste


def troncon(geom, **props):
    base = {"ame_d": None, "ame_g": None, "code_com_d": None, "code_com_g": None,
            "d_service": "2020-01-01", "date_maj": "2026-09-30"}
    base.update(props)
    return {"type": "Feature", "properties": base, "geometry": geom}


def bnac():
    L = lambda code, dy=0.0: {"type": "LineString", "coordinates": ligne(code, dy=dy)}  # noqa: E731
    return {"type": "FeatureCollection", "features": [
        troncon(L("63"), ame_d="PISTE CYCLABLE", ame_g="AUCUN", code_com_d="63001", code_com_g="63001"),
        troncon(L("63", 0.01), ame_d="BANDE CYCLABLE", ame_g="Bande cyclable",
                code_com_d="63002", code_com_g="63002"),
        troncon(L("63", 0.02), ame_d="VOIE VERTE", ame_g="VOIE VERTE", code_com_d="63003", code_com_g="63003"),
        troncon(L("69"), ame_d="DOUBLE SENS CYCLABLE NON MATERIALISE"),  # sans code commune
        troncon(L("63", 0.03), ame_d="AUCUN", ame_g="AUCUN", code_com_d="63001", code_com_g="63001"),
        troncon({"type": "MultiLineString", "coordinates": [ligne("75"), ligne("75", dy=0.01)]},
                ame_d="COULOIR BUS+VELO", code_com_d="75001", date_maj="2026-10-01"),
        troncon(L("2A"), ame_g="PISTE CYCLABLE", code_com_g="2A099"),  # code absent de la table : repli sur le préfixe
        troncon(L("01"), ame_d="PISTE CYCLABLE", code_com_d="97411"),  # outre-mer : ignoré
        troncon(None, ame_d="PISTE CYCLABLE", code_com_d="63001"),     # géométrie vide
    ]}


def jeu_datagouv():
    base = "https://static.data.gouv.fr/resources/amenagements-cyclables-france-metropolitaine/"
    return {"id": amenagements.ID_JEU, "resources": [
        {"title": "france-20260901.geojson", "format": "geojson",
         "url": base + "ancien.geojson", "last_modified": "2026-09-01T03:05:15"},
        {"title": "france-20261001.parquet", "format": "parquet",
         "url": base + "x.parquet", "last_modified": "2026-10-01T03:05:15"},
        {"title": "france-20261001.geojson", "format": "geojson",
         "url": base + "france-20261001.geojson", "last_modified": "2026-10-01T03:05:04"},
    ]}


@pytest.fixture
def monde(tmp_path):
    """Écrit tous les fichiers fictifs et renvoie {url: chemin} + infos utiles."""
    d = tmp_path / "sources"
    d.mkdir()
    urls = {}
    urls[departements.URL_CONTOURS] = ecrire(d, "contours.geojson", contours())
    urls[communes.URL_COMMUNES] = ecrire(d, "communes.json", liste_communes())
    urls[amenagements.URL_API_JEU] = ecrire(d, "jeu.json", jeu_datagouv())
    urls["https://static.data.gouv.fr/resources/amenagements-cyclables-france-metropolitaine/"
         "france-20261001.geojson"] = ecrire(d, "bnac.geojson", bnac())

    G = "https://gbfs.example/"
    s63a, s63b = centre("63", 0.05, 0.05), centre("63", -0.05, 0.05)

    # Système A : GBFS 2.2, stations, flux en français
    urls[G + "a/gbfs.json"] = ecrire(d, "a.json", {"version": "2.2", "data": {"fr": {"feeds": [
        {"name": "system_information", "url": G + "a/si"},
        {"name": "station_information", "url": G + "a/info"},
        {"name": "station_status", "url": G + "a/status"}]}}})
    urls[G + "a/si"] = ecrire(d, "a_si.json", {"data": {"name": "Vélo Fictif A"}})
    urls[G + "a/info"] = ecrire(d, "a_info.json", {"data": {"stations": [
        {"station_id": "1", "name": "Jaude", "lat": s63a[1], "lon": s63a[0], "capacity": 20},
        {"station_id": "2", "name": "Gare", "lat": s63b[1], "lon": s63b[0]},
        {"station_id": "3", "name": "Fermée", "lat": s63b[1] + 0.01, "lon": s63b[0]},
        {"station_id": "4", "name": "Sans coordonnées"}]}})
    urls[G + "a/status"] = ecrire(d, "a_status.json", {"data": {"stations": [
        {"station_id": "1", "num_bikes_available": 7, "is_installed": True},
        {"station_id": "2", "num_bikes_available": 3, "is_installed": 1},
        {"station_id": "3", "num_bikes_available": 9, "is_installed": False}]}})

    # Système B : GBFS 3.0, vélos + trottinettes, noms multilingues, free-floating
    s75 = centre("75", 0.02, 0.02)
    urls[G + "b/gbfs.json"] = ecrire(d, "b.json", {"version": "3.0", "data": {"feeds": [
        {"name": "vehicle_types", "url": G + "b/types"},
        {"name": "station_information", "url": G + "b/info"},
        {"name": "station_status", "url": G + "b/status"},
        {"name": "vehicle_status", "url": G + "b/vehicles"}]}})
    urls[G + "b/types"] = ecrire(d, "b_types.json", {"data": {"vehicle_types": [
        {"vehicle_type_id": "velo", "form_factor": "bicycle"},
        {"vehicle_type_id": "cargo", "form_factor": "cargo_bicycle"},
        {"vehicle_type_id": "trott", "form_factor": "scooter_standing"}]}})
    urls[G + "b/info"] = ecrire(d, "b_info.json", {"data": {"stations": [
        {"station_id": "x", "name": [{"text": "Châtelet", "language": "fr"}], "lat": s75[1], "lon": s75[0]},
        {"station_id": "y", "name": [{"text": "Trott only", "language": "fr"}], "lat": s75[1] + 0.01,
         "lon": s75[0]}]}})
    urls[G + "b/status"] = ecrire(d, "b_status.json", {"data": {"stations": [
        {"station_id": "x", "num_vehicles_available": 10, "vehicle_types_available": [
            {"vehicle_type_id": "velo", "count": 4}, {"vehicle_type_id": "cargo", "count": 1},
            {"vehicle_type_id": "trott", "count": 5}]},
        {"station_id": "y", "num_vehicles_available": 6, "vehicle_types_available": [
            {"vehicle_type_id": "trott", "count": 6}]}]}})
    v75 = centre("75", -0.1, -0.1)
    urls[G + "b/vehicles"] = ecrire(d, "b_veh.json", {"data": {"vehicles": [
        {"vehicle_id": "1", "lat": v75[1], "lon": v75[0], "vehicle_type_id": "velo"},
        {"vehicle_id": "2", "lat": v75[1], "lon": v75[0], "vehicle_type_id": "trott"},
        {"vehicle_id": "3", "lat": v75[1], "lon": v75[0], "vehicle_type_id": "velo", "is_disabled": True},
        {"vehicle_id": "4", "station_id": "x", "vehicle_type_id": "velo"}]}})

    # Système C : GBFS 1.0, free-floating uniquement (vélos implicites)
    v69 = centre("69", 0.1, 0.1)
    urls[G + "c/gbfs.json"] = ecrire(d, "c.json", {"data": {"en": {"feeds": [
        {"name": "free_bike_status", "url": G + "c/bikes"}]}}})
    urls[G + "c/bikes"] = ecrire(d, "c_bikes.json", {"data": {"bikes": [
        {"bike_id": str(i), "lat": v69[1], "lon": v69[0], "is_reserved": 0, "is_disabled": 0}
        for i in range(5)] + [{"bike_id": "loin", "lat": -21.1, "lon": 55.5}]}})

    # Système D : trottinettes seulement (doit être écarté)
    urls[G + "d/gbfs.json"] = ecrire(d, "d.json", {"version": "2.3", "data": {"fr": {"feeds": [
        {"name": "vehicle_types", "url": G + "d/types"},
        {"name": "free_bike_status", "url": G + "d/bikes"}]}}})
    urls[G + "d/types"] = ecrire(d, "d_types.json", {"data": {"vehicle_types": [
        {"vehicle_type_id": "t", "form_factor": "scooter"}]}})
    urls[G + "d/bikes"] = ecrire(d, "d_bikes.json", {"data": {"bikes": [
        {"bike_id": "1", "lat": v69[1], "lon": v69[0], "vehicle_type_id": "t"}]}})

    # Système F : flux publiés séparément, sans gbfs.json (cas d'Amiens, Pompey…)
    s33 = centre("33", 0.03, 0.03)
    urls[G + "f/station_information.json"] = ecrire(d, "f_info.json", {"data": {"stations": [
        {"station_id": "f1", "name": "Quinconces", "lat": s33[1], "lon": s33[0]}]}})
    urls[G + "f/station_status.json"] = ecrire(d, "f_status.json", {"data": {"stations": [
        {"station_id": "f1", "num_bikes_available": 2, "num_docks_available": 8}]}})

    # Système H : vehicle_types en panne (cas de Pony Marseille) -> vélos supposés
    s44 = centre("44", 0.03, 0.03)
    urls[G + "h/gbfs.json"] = ecrire(d, "h.json", {"data": {"fr": {"feeds": [
        {"name": "vehicle_types", "url": G + "h/types-en-panne"},
        {"name": "station_information", "url": G + "h/info"},
        {"name": "station_status", "url": G + "h/status"}]}}})
    urls[G + "h/info"] = ecrire(d, "h_info.json", {"data": {"stations": [
        {"station_id": "h1", "name": "Commerce", "lat": s44[1], "lon": s44[0]}]}})
    urls[G + "h/status"] = ecrire(d, "h_status.json", {"data": {"stations": [
        {"station_id": "h1", "num_bikes_available": 4}]}})

    # Jeu G : le système A publié une deuxième fois sous une autre adresse (cas de Dott)
    urls[G + "a-copie/gbfs.json"] = urls[G + "a/gbfs.json"]

    # Système E : flux en panne (URL absente de la table -> erreur simulée)
    jeux = [
        {"title": "VLS A", "type": "bike-scooter-sharing", "resources": [
            {"format": "gbfs", "url": G + "a/gbfs.json"}, {"format": "csv", "url": G + "a.csv"}]},
        {"title": "VLS B", "type": "vehicles-sharing", "sub_types": ["bicycle", "scooter"], "resources": [
            {"format": "gbfs", "url": G + "b/gbfs.json"}]},
        {"title": "VLS C", "type": "vehicles-sharing", "resources": [
            {"format": "gbfs", "url": G + "c/gbfs.json"},
            {"format": "gbfs", "url": G + "c/gbfs.json"}]},  # doublon
        {"title": "Opérateur D", "type": "vehicles-sharing", "resources": [
            {"format": "gbfs", "url": G + "d/gbfs.json"}]},
        {"title": "VLS E en panne", "type": "bike-scooter-sharing", "resources": [
            {"format": "gbfs", "url": G + "e/gbfs.json"}]},
        {"title": "VLS F flux séparés", "type": "vehicles-sharing", "resources": [
            {"format": "gbfs", "url": G + "f/station_information.json"},
            {"format": "gbfs", "url": G + "f/station_status.json"}]},
        {"title": "VLS A national", "type": "vehicles-sharing", "resources": [
            {"format": "gbfs", "url": G + "a-copie/gbfs.json"}]},
        {"title": "Vélos H", "type": "vehicles-sharing", "resources": [
            {"format": "gbfs", "url": G + "h/gbfs.json"}]},
        {"title": "Autopartage", "type": "vehicles-sharing", "sub_types": ["carsharing"], "resources": [
            {"format": "gbfs", "url": G + "auto/gbfs.json"}]},
        {"title": "Horaires bus", "type": "public-transit", "resources": [{"format": "GTFS", "url": "x"}]},
    ]
    urls[vls.URL_API_JEUX] = ecrire(d, "transport.json", jeux)
    return {"urls": urls, "dossier": tmp_path}
