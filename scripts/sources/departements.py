"""Contours des départements métropolitains (dépôt gregoiredavid/france-geojson).

Sert à trois choses :
  - la géométrie affichée sur la carte ;
  - la liste de référence des 96 départements métropolitains ;
  - retrouver le département d'un point (station VLS, vélo en free-floating).
"""

from __future__ import annotations

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

URL_CONTOURS = (
    "https://raw.githubusercontent.com/gregoiredavid/france-geojson/master/"
    "departements-version-simplifiee.geojson"
)


def arrondir_coordonnees(coords, decimales: int = 4):
    """Arrondit récursivement les coordonnées (4 décimales ≈ 10 m) pour alléger le fichier."""
    if isinstance(coords[0], (int, float)):
        return [round(c, decimales) for c in coords]
    return [arrondir_coordonnees(c, decimales) for c in coords]


def charger_contours(client) -> list[dict]:
    """Renvoie une liste de {code, nom, geometrie} triée par code."""
    donnees = client.get_json(URL_CONTOURS)
    departements = []
    for f in donnees.get("features", []):
        props = f.get("properties") or {}
        code, nom = props.get("code"), props.get("nom")
        if not code or not f.get("geometry"):
            continue
        geom = f["geometry"]
        departements.append({
            "code": str(code),
            "nom": nom or str(code),
            "geometrie": {"type": geom["type"],
                          "coordinates": arrondir_coordonnees(geom["coordinates"])},
        })
    if len(departements) < 90:
        raise ValueError(f"Contours incomplets : {len(departements)} départements seulement")
    return sorted(departements, key=lambda d: d["code"])


class LocalisateurDepartement:
    """Trouve le département contenant un point (lon, lat), via un index spatial."""

    def __init__(self, departements: list[dict]):
        self.codes = [d["code"] for d in departements]
        self.formes = [shape(d["geometrie"]) for d in departements]
        self.index = STRtree(self.formes)

    def trouver(self, lon: float, lat: float) -> str | None:
        p = Point(lon, lat)
        for i in self.index.query(p):
            if self.formes[i].covers(p):
                return self.codes[i]
        # Les contours sont simplifiés : un point sur le littoral (port, front de mer) peut
        # tomber juste à côté. On le rattache au département le plus proche, à 0,05° près (~5 km).
        proches = self.index.query_nearest(p, max_distance=0.05)
        return self.codes[int(proches[0])] if len(proches) else None
