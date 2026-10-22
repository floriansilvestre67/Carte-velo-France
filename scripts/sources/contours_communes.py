"""Contours des communes (Etalab, « contours administratifs », simplifiés à 100 m).

Choix : un seul fichier national compressé (≈ 8 Mo) plutôt qu'une centaine d'appels à
geo.api.gouv.fr. L'adresse « latest » d'Etalab pointe toujours vers le dernier millésime.
Le fichier est lu en flux (ijson) et découpé par département.

Sert à :
  - dessiner le contour de la ville choisie (contours/{dep}.geojson, chargé à la demande) ;
  - rattacher à leur commune les points sans code INSEE (stations VLS, lieux…).
"""

from __future__ import annotations

import gzip
from pathlib import Path

import ijson
from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from sources.communes import commune_entiere, departement_du_code
from sources.departements import arrondir_coordonnees

URL_CONTOURS = ("https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/latest/geojson/"
                "communes-100m.geojson.gz")
CLES_CODE = ("code", "insee", "INSEE_COM", "codgeo", "com")


def _code(props: dict) -> str | None:
    for k in CLES_CODE:
        if props.get(k):
            return str(props[k]).strip().upper().zfill(5)
    return None


def lire(chemin: Path, codes_valides: set[str]) -> dict:
    """{"par_dep": {dep: [feature, …]}, "diagnostic": {...}} (coordonnées arrondies à 1e-4)."""
    ouvrir = gzip.open if str(chemin).endswith(".gz") else open
    par_code: dict[str, dict] = {}
    morceaux: dict[str, list] = {}       # arrondissements à fusionner si la commune entière manque
    diag = {"objets": 0, "cles_proprietes": None, "arrondissements": 0}
    with ouvrir(chemin, "rb") as f:
        for feat in ijson.items(f, "features.item", use_float=True):
            diag["objets"] += 1
            props = feat.get("properties") or {}
            if diag["cles_proprietes"] is None:
                diag["cles_proprietes"] = sorted(props.keys())
            code = _code(props)
            geom = feat.get("geometry")
            if not code or not geom:
                continue
            entiere = commune_entiere(code)
            if entiere != code:
                diag["arrondissements"] += 1
                morceaux.setdefault(entiere, []).append(geom)
                continue
            if departement_du_code(code) not in codes_valides:
                continue
            par_code[code] = {"nom": props.get("nom"), "geom": geom}
    # Paris, Lyon, Marseille : si seuls les arrondissements sont fournis, on les réunit
    for entiere, geoms in morceaux.items():
        if entiere not in par_code and departement_du_code(entiere) in codes_valides:
            union = unary_union([shape(g) for g in geoms])
            par_code[entiere] = {"nom": None, "geom": union.__geo_interface__}
    par_dep: dict[str, list] = {}
    for code, c in par_code.items():
        g = c["geom"]
        par_dep.setdefault(departement_du_code(code), []).append({
            "type": "Feature", "properties": {"code": code},
            "geometry": {"type": g["type"], "coordinates": arrondir_coordonnees(_listes(g["coordinates"]))}})
    diag["communes"] = len(par_code)
    diag["paris_entier"] = "75056" in par_code
    if len(par_code) < 1000:
        raise ValueError(f"Contours des communes incomplets : {len(par_code)} communes lues")
    return {"par_dep": par_dep, "diagnostic": diag}


def _listes(coords):
    """Les géométries issues de shapely utilisent des tuples : on revient à des listes JSON."""
    if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
        return list(coords)
    return [_listes(c) for c in coords]


class LocalisateurCommune:
    """Trouve la commune contenant un point (lon, lat)."""

    def __init__(self, par_dep: dict[str, list]):
        self.codes, self.formes = [], []
        for feats in par_dep.values():
            for f in feats:
                self.codes.append(f["properties"]["code"])
                self.formes.append(shape(f["geometry"]))
        self.index = STRtree(self.formes)

    def trouver(self, lon: float, lat: float) -> str | None:
        p = Point(lon, lat)
        for i in self.index.query(p):
            if self.formes[i].covers(p):
                return self.codes[i]
        return None


def calculer(client, dossier_travail: Path, codes_valides: set[str]) -> dict:
    chemin = client.telecharger(URL_CONTOURS, dossier_travail / "communes-100m.geojson.gz")
    return lire(chemin, codes_valides)
