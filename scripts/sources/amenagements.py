"""Aménagements cyclables (jeu national data.gouv.fr, schéma BNAC).

Le fichier GeoJSON national pèse environ 300 Mo : on le télécharge sur le disque
puis on le lit objet par objet avec ijson, sans jamais le charger entièrement
en mémoire.

Règles de comptage (expliquées aussi sur la page « Sources et méthode ») :
  - chaque tronçon décrit deux côtés de la voie : droit (ame_d) et gauche (ame_g) ;
  - chaque côté aménagé compte pour la longueur du tronçon ;
  - exception : une voie verte décrite à l'identique des deux côtés n'est comptée
    qu'une fois (c'est une seule voie, pas deux) ;
  - la longueur est géodésique (ellipsoïde WGS84, pyproj) ;
  - le département vient du code INSEE de la commune du côté concerné
    (code_com_d / code_com_g) ; à défaut, de la position du tronçon.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import ijson
from pyproj import Geod

ID_JEU = "60a37b7f303fdf4f2654b73d"
URL_API_JEU = f"https://www.data.gouv.fr/api/1/datasets/{ID_JEU}/"

CATEGORIES = ["pistes", "bandes", "voies_vertes", "double_sens", "autres"]

_GEOD = Geod(ellps="WGS84")


def normaliser(valeur) -> str:
    """'Piste cyclable ' -> 'PISTE CYCLABLE' (majuscules, sans accents ni espaces superflus)."""
    if not valeur:
        return ""
    texte = unicodedata.normalize("NFKD", str(valeur))
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return " ".join(texte.upper().split())


def categorie(type_amenagement) -> str | None:
    """Range une valeur du schéma BNAC dans l'une des 5 catégories, ou None si pas d'aménagement."""
    t = normaliser(type_amenagement)
    if t in ("", "AUCUN", "NONE", "NULL"):
        return None
    if t.startswith("DOUBLE SENS"):
        return "double_sens"
    if t == "PISTE CYCLABLE":
        return "pistes"
    if t == "BANDE CYCLABLE":
        return "bandes"
    if t == "VOIE VERTE":
        return "voies_vertes"
    return "autres"


def trouver_ressource(client) -> dict:
    """Interroge l'API data.gouv.fr et renvoie la ressource GeoJSON nationale la plus récente."""
    jeu = client.get_json(URL_API_JEU)
    ressources = [r for r in jeu.get("resources", [])
                  if normaliser(r.get("format")) == "GEOJSON" and r.get("url")]
    if not ressources:
        raise ValueError("Aucune ressource GeoJSON dans le jeu « Aménagements cyclables »")
    # Les fichiers nationaux s'appellent « france-AAAAMMJJ.geojson » : on les préfère.
    nationales = [r for r in ressources if str(r.get("title", "")).lower().startswith("france")]
    candidates = nationales or ressources
    return max(candidates, key=lambda r: r.get("last_modified") or "")


def longueur_km(geometrie) -> float:
    """Longueur géodésique en km d'une LineString ou MultiLineString GeoJSON."""
    if not geometrie:
        return 0.0
    t = geometrie.get("type")
    coords = geometrie.get("coordinates") or []
    if t == "LineString":
        lignes = [coords]
    elif t == "MultiLineString":
        lignes = coords
    else:
        return 0.0
    total = 0.0
    for ligne in lignes:
        if len(ligne) < 2:
            continue
        lons = [p[0] for p in ligne]
        lats = [p[1] for p in ligne]
        total += _GEOD.line_length(lons, lats)
    return total / 1000.0


def premier_point(geometrie):
    coords = (geometrie or {}).get("coordinates") or []
    if (geometrie or {}).get("type") == "MultiLineString":
        coords = coords[0] if coords else []
    return coords[0] if coords else None


def departement_de_commune(code_commune, table: dict[str, str]) -> str | None:
    if not code_commune:
        return None
    code = str(code_commune).strip().zfill(5)
    if code in table:
        return table[code]
    # Repli : préfixe du code INSEE (2 caractères en métropole, 3 outre-mer)
    return code[:3] if code.startswith("97") else code[:2]


def agreger(chemin_geojson: Path, table_communes: dict[str, str], localisateur,
            codes_valides: set[str]) -> dict:
    """Parcourt le fichier en streaming et cumule les km par département et par catégorie."""
    km = {code: {c: 0.0 for c in CATEGORIES} for code in codes_valides}
    stats = {"troncons": 0, "troncons_sans_departement": 0, "km_hors_metropole": 0.0,
             "date_maj_max": None}

    with open(chemin_geojson, "rb") as f:
        for feature in ijson.items(f, "features.item", use_float=True):
            stats["troncons"] += 1
            p = feature.get("properties") or {}
            geom = feature.get("geometry")

            cote_d, cote_g = categorie(p.get("ame_d")), categorie(p.get("ame_g"))
            if cote_d is None and cote_g is None:
                continue

            date_maj = p.get("date_maj")
            if date_maj and (stats["date_maj_max"] is None or str(date_maj) > stats["date_maj_max"]):
                stats["date_maj_max"] = str(date_maj)[:10]

            longueur = longueur_km(geom)
            if longueur <= 0:
                continue

            dep_d = departement_de_commune(p.get("code_com_d"), table_communes)
            dep_g = departement_de_commune(p.get("code_com_g"), table_communes)
            # Si un côté n'a pas de commune, on reprend celle de l'autre côté,
            # puis en dernier recours la position géographique du tronçon.
            if dep_d is None or dep_g is None:
                secours = dep_d or dep_g
                if secours is None:
                    pt = premier_point(geom)
                    secours = localisateur.trouver(pt[0], pt[1]) if pt else None
                dep_d, dep_g = dep_d or secours, dep_g or secours

            cotes = [(cote_d, dep_d), (cote_g, dep_g)]
            # Voie verte identique des deux côtés : une seule voie
            if cote_d == cote_g == "voies_vertes" and dep_d == dep_g:
                cotes = [(cote_d, dep_d)]

            for cat, dep in cotes:
                if cat is None:
                    continue
                if dep is None:
                    stats["troncons_sans_departement"] += 1
                elif dep in km:
                    km[dep][cat] += longueur
                else:
                    stats["km_hors_metropole"] += longueur

    if stats["troncons"] == 0:
        raise ValueError("Le fichier des aménagements ne contient aucun tronçon")
    return {"km": km, "stats": stats}


def calculer(client, dossier_travail: Path, table_communes, localisateur, codes_valides) -> dict:
    ressource = trouver_ressource(client)
    print(f"  Ressource : {ressource.get('title')} ({ressource['url']})")
    chemin = client.telecharger(ressource["url"], dossier_travail / "amenagements.geojson")
    resultat = agreger(chemin, table_communes, localisateur, codes_valides)
    resultat["ressource"] = {"titre": ressource.get("title"), "url": ressource["url"],
                             "publiee_le": (ressource.get("last_modified") or "")[:10] or None}
    return resultat
