"""Données fictives au format réel des sources, pour tester sans réseau.

Le « monde fictif » :
  - 96 départements métropolitains, chacun un carré de 0,5° (vrais codes, faux contours) ;
  - 12 communes par département (geo.api.gouv.fr, surface en hectares) ;
  - quelques tronçons BNAC aux cas particuliers connus ;
  - 5 systèmes GBFS : v1.0, v2.2, v3.0, un système de trottinettes, un flux en panne,
    plus un jeu d'autopartage à ignorer.
"""

import csv
import gzip
import json
import sys
import zipfile
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "scripts"))

from sources import (accidents, amenagements, baac, communes, contours_communes, cyclistes, departements, poi,  # noqa: E402
                     regions, stationnement, vls)

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


def contours_communes_fictifs():
    """Chaque département est découpé en 12 communes (grille 4 × 3).
    Paris n'est fourni que par deux arrondissements (moitiés gauche et droite), à fusionner."""
    feats = []
    for code in CODES:
        lon0, lat0 = carre(code)
        if code == "75":
            for k, (a, b) in enumerate([(0, 0.25), (0.25, 0.5)], start=1):
                anneau = [[lon0 + a, lat0], [lon0 + b, lat0], [lon0 + b, lat0 + TAILLE], [lon0 + a, lat0 + TAILLE], [lon0 + a, lat0]]
                feats.append({"type": "Feature", "properties": {"code": f"7510{k}", "nom": f"Paris {k}e"},
                              "geometry": {"type": "Polygon", "coordinates": [anneau]}})
            continue
        for k in range(12):
            w, h = TAILLE / 4, TAILLE / 3
            x, y = lon0 + (k % 4) * w, lat0 + (k // 4) * h
            anneau = [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]
            code_com = "69123" if (code == "69" and k == 0) else f"{code}{k + 1:03d}"
            feats.append({"type": "Feature", "properties": {"code": code_com, "nom": "x", "departement": code},
                          "geometry": {"type": "Polygon", "coordinates": [anneau]}})
    return {"type": "FeatureCollection", "features": feats}


def csv_texte(lignes, sep=","):
    return "\n".join(sep.join(str(x) for x in l) for l in lignes) + "\n"


def stationnement_fictif(d: Path, urls: dict) -> None:
    """Indicateurs Ecolab (2 relevés, on garde le plus récent) et emplacements OSM."""
    S = "https://static.data.gouv.fr/resources/stationnement/"
    places_dep = [["date_mesure", "geocode_departement", "libelle_departement", "type_accroche", "valeur"],
                  ["2024-01-01T00:00:00", "63", "Puy-de-Dôme", "cadre et roue", 100],
                  ["2025-01-01T00:00:00", "63", "Puy-de-Dôme", "cadre et roue", 500],
                  ["2025-01-01T00:00:00", "63", "Puy-de-Dôme", "cadre", 20],
                  ["2025-01-01T00:00:00", "63", "Puy-de-Dôme", "roue", 300],
                  ["2025-01-01T00:00:00", "63", "Puy-de-Dôme", "sans accroche", 80],
                  ["2025-01-01T00:00:00", "75", "Paris", "cadre et roue", 1000]]
    places_com = [["date_mesure", "geocode_commune", "libelle_commune", "type_accroche", "valeur"],
                  ["2025-01-01T00:00:00", "63001", "Commune 63-1", "cadre et roue", 40],
                  ["2025-01-01T00:00:00", "63001", "Commune 63-1", "roue", 10],
                  ["2025-01-01T00:00:00", "75101", "Paris 1er", "cadre", 7],      # arrondissement -> Paris
                  ["2025-01-01T00:00:00", "75056", "Paris", "cadre et roue", 993]]
    secu_dep = [["date_mesure", "geocode_departement", "libelle_departement", "numerateur", "denominateur", "valeur"],
                ["2025-01-01", "63", "Puy-de-Dôme", 520, 100000, 5.2]]
    secu_com = [["date_mesure", "geocode_commune", "libelle_commune", "numerateur", "denominateur", "valeur"],
                ["2025-01-01", "63001", "Commune 63-1", 40, 62001, 0.645]]
    for id_jeu, fichiers in ((stationnement.ID_PLACES, {"departement": places_dep, "commune": places_com}),
                             (stationnement.ID_SECURISEES, {"departement": secu_dep, "commune": secu_com})):
        ressources = [{"title": "Description des champs", "url": S + id_jeu + "/desc.csv"}]
        for niveau, lignes in fichiers.items():
            url = S + id_jeu + f"/{niveau}.csv"
            chemin = d / f"stat-{id_jeu}-{niveau}.csv"
            chemin.write_text(csv_texte(lignes, ";" if niveau == "commune" else ","), encoding="utf-8")
            urls[url] = chemin
            ressources.append({"title": f"Indicateur - {niveau}", "url": url})
        urls[stationnement.URL_API.format(id_jeu)] = ecrire(d, f"jeu-{id_jeu}.json", {"resources": ressources})

    lon63, lat63 = centre("63")
    pts = [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon63, lat63]},
         "properties": {"code_com": "63001", "capacite": 10, "capacite_cargo": 2, "type_accroche": "cadre et roue",
                        "mobilier": "arceau", "acces": "aucun", "gratuit": "true", "protection": "accès libre",
                        "couverture": "false", "surveillance": "false"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon63 + 0.01, lat63]},
         "properties": {"code_com": "63001", "capacite": None, "type_accroche": "roue", "mobilier": "ratelier"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon63 + 0.02, lat63]},   # sans code commune
         "properties": {"capacite": 6, "type_accroche": "sans accroche", "protection": "box individuel fermé",
                        "couverture": "true", "surveillance": "true", "gratuit": "false"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [55.45, -20.9]},
         "properties": {"code_com": "97411", "capacite": 4}},                                    # outre-mer
    ]
    chemin_zip = d / "osm.zip"
    with zipfile.ZipFile(chemin_zip, "w") as z:
        z.writestr("bicycle_parking.geojson", json.dumps({"type": "FeatureCollection", "features": pts}))
    url_zip = "https://geodatamine.example/bicycle_parking_geojson.zip"
    urls[url_zip] = chemin_zip
    urls[stationnement.URL_API.format(stationnement.ID_OSM)] = ecrire(d, "jeu-osm.json", {"resources": [
        {"title": "Format CSV brut", "format": "csv", "url": "https://geodatamine.example/bicycle_parking.csv"},
        {"title": "Format GeoJSON", "format": "geojson.zip", "url": url_zip}]})


def poi_fictifs(d: Path, urls: dict) -> None:
    """Exports DATAtourisme (place, tour, product), Mérimée et Muséofile au format réel."""
    D = "https://www.datatourisme.fr/ontology/core#"
    lon, lat = centre("63")
    entete = ["Nom_du_POI", "Categories_de_POI", "Latitude", "Longitude", "Adresse_postale",
              "Code_postal_et_commune", "Description", "URI_ID_du_POI"]
    def l(nom, cats, la, lo, uri, desc=""):
        return [nom, "|".join(D + c for c in ["PointOfInterest", "PlaceOfInterest"] + cats), la, lo, "", "", desc, uri]
    place = [entete,
             l("Musée d'art Roger-Quilliot", ["CulturalSite", "Museum"], lat, lon, "u1", "Un musée, avec, des virgules"),
             l("Hôtel du Centre", ["Accommodation", "Hotel"], lat, lon, "u2"),
             l("Église Notre-Dame", ["CulturalSite", "ReligiousSite", "Church"], lat + 0.01, lon, "u3"),
             l("Jardin Lecoq", ["ParkAndGarden"], lat + 0.02, lon, "u4"),
             l("Plage du lac", ["NaturalHeritage", "Beach"], lat + 0.03, lon, "u5"),
             l("Médiathèque", ["CulturalSite", "Library"], lat, lon + 0.01, "u6"),
             l("Site de La Réunion", ["CulturalSite"], -21.1, 55.5, "u7"),
             l("Musée d'art Roger-Quilliot", ["CulturalSite", "Museum"], lat, lon, "u1")]          # doublon d'URI
    tour = [entete, l("Boucle des volcans à vélo", ["Tour", "CyclingTour"], lat - 0.01, lon, "t1"),
            l("Sentier pédestre", ["Tour", "WalkingTour"], lat - 0.02, lon, "t2")]
    product = [entete, l("Location de vélos du lac", ["Product", "Rental", "EquipmentRental"], lat - 0.03, lon, "p1"),
               l("Location de kayaks", ["Product", "Rental", "EquipmentRental"], lat - 0.03, lon + 0.01, "p2")]
    ressources = []
    for nom, lignes in (("place", place), ("tour", tour), ("product", product), ("fma", [entete])):
        chemin = d / f"datatourisme-{nom}.csv"
        with open(chemin, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(lignes)
        url = f"https://static.data.gouv.fr/datatourisme-{nom}.csv"
        urls[url] = chemin
        ressources.append({"title": f"datatourisme-{nom}.csv", "url": url, "format": "csv"})
    urls[poi.URL_API.format(poi.ID_DATATOURISME)] = ecrire(d, "jeu-dt.json", {"resources": ressources})

    # En-têtes tels qu'ils sont dans les vrais fichiers du Ministère (accents, espaces)
    merimee = [["Référence", "Titre éditorial de la notice", "Dénomination de l'édifice", "Typologie de la protection",
                "Format abrégé du siècle de construction", "Coordonnées au format WGS84"],
               ["PA001", "Église Notre-Dame", "église", "classé MH", "12e s.", f"{lat + 0.0101}, {lon}"],   # 11 m de u3
               ["PA002", "Halle aux blés", "halle", "inscrit MH", "19e s.", f"{lat + 0.04}, {lon}"],
               ["PA003", "Sans coordonnées", "croix", "inscrit MH", "", ""]]
    chemin = d / "merimee.csv"
    with open(chemin, "w", encoding="utf-8", newline="") as f:
        csv.writer(f, delimiter=";").writerows(merimee)
    urls["https://culture.example/merimee.csv"] = chemin
    urls[poi.URL_API.format(poi.ID_MERIMEE)] = ecrire(d, "jeu-mh.json", {"resources": [
        {"title": "geojson", "format": "geojson", "url": "https://culture.example/merimee.geojson"},
        {"title": "csv", "format": "csv", "url": "https://culture.example/merimee.csv"}]})
    lon69, lat69 = centre("69")
    museofile = [["Identifiant", "Nom officiel", "Ville", "URL", "Coordonnées", "Atout"],
                 ["M1", "Musée d'art Roger Quilliot", "Clermont", "www.musee.example", f"{lat + 0.0005}, {lon + 0.0005}", ""],
                 ["M2", "Musée des Confluences", "Lyon", "", f"{lat69}, {lon69}", "Sciences et sociétés"]]
    chemin = d / "museofile.csv"
    with open(chemin, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(museofile)
    urls["https://culture.example/museofile.csv"] = chemin
    urls[poi.URL_API.format(poi.ID_MUSEOFILE)] = ecrire(d, "jeu-musees.json", {"resources": [
        {"title": "museofile.csv", "format": "csv", "url": "https://culture.example/museofile.csv"}]})


def liste_communes():
    liste = []
    for n, code in enumerate(CODES):
        for k in range(1, 13):
            liste.append({"code": f"{code}{k:03d}", "nom": f"Commune {code}-{k}", "codeDepartement": code,
                          "codesPostaux": [f"{code.replace('A', '0').replace('B', '0')}{k:03d}"],
                          "population": 1000 * (n + 1) + k, "surface": 2500.0})  # 25 km²
    # Communes à arrondissements, avec leurs vrais codes
    liste.append({"code": "75056", "nom": "Paris", "codeDepartement": "75", "population": 2100000, "surface": 10540.0})
    liste.append({"code": "69123", "nom": "Lyon", "codeDepartement": "69", "population": 520000, "surface": 4787.0})
    liste.append({"code": "97411", "codeDepartement": "974", "population": 150000, "surface": 14000.0})
    liste.append({"code": "99999", "codeDepartement": "63", "surface": 100.0})  # sans population
    return liste


# --------------------------------------------------------------------------
# Fichiers BAAC fictifs : mêmes cas particuliers que dans la réalité
# --------------------------------------------------------------------------

ANCIEN = {"caract": ["Num_Acc", "an", "mois", "jour", "hrmn", "lum", "agg", "int", "atm", "col", "com", "adr",
                     "gps", "lat", "long", "dep"],
          "lieux": ["Num_Acc", "catr", "voie", "circ", "nbv", "situ"],
          "vehicules": ["Num_Acc", "senc", "catv", "occutc", "obs", "obsm", "choc", "manv", "num_veh"],
          "usagers": ["Num_Acc", "place", "catu", "grav", "sexe", "trajet", "secu", "an_nais", "num_veh"]}
NOUVEAU = {"caract": ["Num_Acc", "jour", "mois", "an", "hrmn", "lum", "dep", "com", "agg", "lat", "long"],
           "lieux": ["Num_Acc", "catr", "voie", "circ", "nbv", "vosp", "situ"],
           "vehicules": ["Num_Acc", "id_vehicule", "num_veh", "senc", "catv", "obs", "obsm", "choc", "manv"],
           "usagers": ["Num_Acc", "id_usager", "id_vehicule", "num_veh", "place", "catu", "grav", "sexe",
                       "an_nais", "trajet"]}


def accident_baac(num, dep, com, situ, vehicules, usagers):
    """vehicules : [(num_veh, catv, obsm)] ; usagers : [(num_veh, catu, grav, trajet)]"""
    return {"num": num, "dep": dep, "com": com, "situ": situ, "vehicules": vehicules, "usagers": usagers}


def accidents_baac():
    return {
        # B : Paris, ancien format (« 750 » + « 012 »), piéton heurté par le cycliste
        2010: [accident_baac("201000000002", "750", "012", "1", [("A01", "1", "0")],
                             [("A01", "1", "3", "5"), ("A01", "3", "4", "0")]),
               accident_baac("201000000099", "630", "001", "1", [("A01", "7", "0")], [("A01", "1", "4", "1")])],
        # C : deux cyclistes (vélo + VAE), indemnes, motif et situation non renseignés
        2019: [accident_baac("201900000003", "01", "01005", "0", [("A01", "1", "0"), ("B01", "80", "0")],
                             [("A01", "1", "1", "0"), ("B01", "1", "1", "0")])],
        # E : ancienne commune fusionnée, gravité non renseignée, poids lourd, autre voie spéciale
        2020: [accident_baac("202000000005", "63", "63999", "6", [("A01", "1", "0"), ("B01", "14", "0")],
                             [("A01", "1", "-1", "5"), ("B01", "1", "1", "4")])],
        # A : deux cyclistes, un tué, bus + voiture, sur piste ; F : Corse ; et un accident sans vélo
        2021: [accident_baac("202100000001", "63", "63001", "5",
                             [("A01", "1", "0"), ("B01", "1", "0"), ("C01", "7", "0"), ("D01", "18", "0")],
                             [("A01", "1", "4", "1"), ("B01", "1", "2", "5"), ("C01", "1", "1", "1")]),
               accident_baac("202100000006", "2A", "2A004", "1", [("A01", "1", "0"), ("B01", "33", "0")],
                             [("A01", "1", "4", "5"), ("B01", "1", "4", "5")]),
               accident_baac("202100000098", "63", "63001", "1", [("A01", "7", "0")], [("A01", "1", "3", "1")])],
        # D : outre-mer, à écarter ; identifiant « Accident_Id » dans les caractéristiques (comme en 2022)
        2022: [accident_baac("202200000004", "971", "97101", "1", [("A01", "1", "0")], [("A01", "1", "4", "5")])],
        # G : arrondissement de Lyon
        2023: [accident_baac("202300000007", "69", "69383", "1", [("A01", "1", "0"), ("B01", "7", "0")],
                             [("A01", "1", "4", "5"), ("B01", "1", "1", "1")])],
    }


def baac_fictif(d: Path, urls: dict) -> dict:
    ressources, urls_annee = [], {}
    for annee, accs in accidents_baac().items():
        ancien = annee < 2019
        entetes = ANCIEN if ancien else NOUVEAU
        sep = ("\t" if annee == 2009 else ",") if ancien else ";"
        lignes = {t: [] for t in entetes}
        for a in accs:
            ent_c = list(entetes["caract"])
            if annee == 2022:
                ent_c[0] = "Accident_Id"
            ligne_c = {k: "" for k in ent_c}
            ligne_c.update({ent_c[0]: a["num"], "dep": a["dep"], "com": a["com"]})
            lignes["caract"].append([ligne_c[k] for k in ent_c])
            lignes["lieux"].append([a["num"] if k == "Num_Acc" else a["situ"] if k == "situ" else "1"
                                    for k in entetes["lieux"]])
            for nv, catv, obsm in a["vehicules"]:
                v = {"Num_Acc": a["num"], "num_veh": nv, "catv": catv, "obsm": obsm, "id_vehicule": "154 680 " + nv}
                lignes["vehicules"].append([v.get(k, "0") for k in entetes["vehicules"]])
            for nv, catu, grav, trajet in a["usagers"]:
                u = {"Num_Acc": a["num"], "num_veh": nv, "catu": catu, "grav": grav, "trajet": trajet}
                lignes["usagers"].append([u.get(k, "1") for k in entetes["usagers"]])
        noms = {"caract": "caracteristiques" if ancien else ("carcteristiques" if annee == 2022 else "caract"),
                "lieux": "lieux", "vehicules": "vehicules", "usagers": "usagers"}
        for t, contenu in lignes.items():
            ent = list(entetes[t])
            if t == "caract" and annee == 2022:
                ent[0] = "Accident_Id"
            chemin = d / f"{noms[t]}-{annee}.csv"
            with open(chemin, "w", encoding="cp1252" if ancien else "utf-8", newline="") as f:
                csv.writer(f, delimiter=sep, quoting=csv.QUOTE_MINIMAL if ancien else csv.QUOTE_ALL).writerows([ent] + contenu)
            url = f"https://static.data.gouv.fr/baac/{annee}/{noms[t]}-{annee}.csv"
            urls[url] = chemin
            urls_annee[(annee, t)] = url
            ressources.append({"title": f"{noms[t].capitalize()}_{annee}.csv", "format": "csv", "url": url,
                               "last_modified": "2025-10-21T11:59:00"})
    # Fichiers à ignorer : véhicules immatriculés et documentation
    ressources.append({"title": "vehicules-immatricule-baac-2021.csv", "format": "csv",
                       "url": "https://static.data.gouv.fr/baac/2021/2021.csv"})
    ressources.append({"title": "description-des-bases-de-donnees-annuelles.pdf", "format": "pdf",
                       "url": "https://static.data.gouv.fr/baac/description.pdf"})
    urls[baac.URL_API] = ecrire(d, "jeu-baac.json", {"last_modified": "2025-12-29T09:29:20", "resources": ressources})
    return urls_annee


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
        troncon(L("2A"), ame_g="PISTE CYCLABLE", code_com_g="2A099"),
        troncon(L("75", 0.02), ame_d="PISTE CYCLABLE", code_com_d="75108"),  # arrondissement -> Paris  # code absent de la table : repli sur le préfixe
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


def insee_fictif(d: Path, urls: dict) -> None:
    """Base Insee « Navettes » au format Melodi (une ligne par territoire, mode et année), avec son
    fichier de métadonnées. Cas réels reproduits : 2012 avec vélo et deux-roues confondus (3T4),
    arrondissements (ARM) à ignorer, autres zonages, valeur « K » (comptée ailleurs), décimales."""
    entete = "GEO;GEO_OBJECT;TRANS;AGE;EMPSTA_ENQ;WORK_AREA;RP_MEASURE;FREQ;OBS_STATUS;TIME_PERIOD;OBS_VALUE"
    lignes = [entete]

    def l(geo, objet, trans, an, valeur, statut="A", zone="_T"):
        lignes.append(f"{geo};{objet};{trans};Y_GE15;1;{zone};POP;A;{statut};{an};{valeur}")

    for code in CODES:
        for k in range(1, 13):
            com = f"{code}{k:03d}"
            l(com, "COM", "3T4", 2012, "99")                 # année sans vélo distingué : ignorée
            l(com, "COM", "3", 2017, f"{k}.4")
            l(com, "COM", "3", 2023, f"{2 * k}.4")
            l(com, "COM", "4", 2023, "50")                   # deux-roues motorisés : ignorés
            l(com, "COM", "_T", 2017, "400.5")
            l(com, "COM", "_T", 2023, "410")
            l(com, "COM", "_T", 2023, "77", zone="21")       # ventilation par lieu de travail : ignorée
            l(com, "BV2022", "3", 2023, "999")               # autre zonage : ignoré
        l(code, "DEP", "3", 2017, str(sum(k + 0.4 for k in range(1, 13))))
        l(code, "DEP", "3", 2023, str(sum(2 * k + 0.4 for k in range(1, 13))))
    l("84", "REG", "3", 2017, "1234")
    l("84", "REG", "3", 2023, "2345")
    l("75056", "COM", "3", 2017, "50000")
    l("75056", "COM", "3", 2023, "90000")
    l("75056", "COM", "_T", 2023, "1000000")
    l("75101", "ARM", "3", 2023, "900")                      # arrondissement : ignoré
    l("69123", "COM", "3", 2017, "18000")
    l("69123", "COM", "3", 2023, "0", statut="K")            # valeur comptée ailleurs : inconnue
    l("00000", "COM", "3", 2023, "5")                        # code inconnu
    meta = ["COD_VAR;LIB_VAR;COD_MOD;LIB_MOD;GEO_OBJECT",
            "TRANS;Mode de transport;1;Pas de transport;",
            "TRANS;Mode de transport;3T4;Vélo ou deux-roues motorisé;",
            "TRANS;Mode de transport;4;Deux-roues motorisé;",
            "TRANS;Mode de transport;3;Vélo (y compris à assistance électrique);",
            "TRANS;Mode de transport;_T;Total;"]
    chemin = d / "insee.zip"
    with zipfile.ZipFile(chemin, "w") as z:
        z.writestr("DS_RP_NAVETTES_PRINC_2023_data.csv", "\n".join(lignes))
        z.writestr("DS_RP_NAVETTES_PRINC_2023_metadata.csv", "\n".join(meta))
    urls[cyclistes.URL_FICHIER] = chemin


@pytest.fixture
def monde(tmp_path):
    """Écrit tous les fichiers fictifs et renvoie {url: chemin} + infos utiles."""
    d = tmp_path / "sources"
    d.mkdir()
    urls = {}
    urls[departements.URL_CONTOURS] = ecrire(d, "contours.geojson", contours())
    urls[communes.URL_COMMUNES] = ecrire(d, "communes.json", liste_communes())
    chemin_gz = d / "communes-100m.geojson.gz"
    with gzip.open(chemin_gz, "wt", encoding="utf-8") as f:
        json.dump(contours_communes_fictifs(), f)
    urls[contours_communes.URL_CONTOURS] = chemin_gz
    urls[communes.URL_ARRONDISSEMENTS] = ecrire(d, "arrondissements.json", [
        {"nom": "Paris 1er Arrondissement", "code": "75101", "codesPostaux": ["75001"], "population": 15000, "codeDepartement": "75"},
        {"nom": "Lyon 3e Arrondissement", "code": "69383", "codesPostaux": ["69003"], "population": 100000, "codeDepartement": "69"}])
    stationnement_fictif(d, urls)
    poi_fictifs(d, urls)
    urls[communes.URL_DELEGUEES] = ecrire(d, "deleguees.json", [
        {"code": "63999", "nom": "Ancienne commune", "chefLieu": "63001"},
        {"code": "63001", "nom": "Chef-lieu lui-même", "chefLieu": "63001"}])
    urls_baac = baac_fictif(d, urls)
    # 13 régions fictives ; le 63 et le 69 sont dans la même (84), comme en vrai
    regs = [{"code": f"R{i}", "nom": f"Région {i}"} for i in range(12)] + [{"code": "84", "nom": "Auvergne-Rhône-Alpes"}]
    deps_api = [{"code": c, "nom": f"Département {c}",
                 "codeRegion": "84" if c in ("63", "69", "01") else f"R{CODES.index(c) % 12}"} for c in CODES]
    deps_api.append({"code": "974", "nom": "La Réunion", "codeRegion": "04"})
    urls[regions.URL_DEPARTEMENTS] = ecrire(d, "deps_api.json", deps_api)
    urls[regions.URL_REGIONS] = ecrire(d, "regions.json", regs)
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
        {"station_id": "x", "name": [{"text": "Châtelet", "language": "fr"}], "lat": s75[1], "lon": s75[0],
         "is_virtual_station": True},
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
    insee_fictif(d, urls)
    return {"urls": urls, "dossier": tmp_path, "urls_baac": urls_baac}
