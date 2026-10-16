"""Région de chaque département (geo.api.gouv.fr)."""

from __future__ import annotations

URL_DEPARTEMENTS = "https://geo.api.gouv.fr/departements?fields=nom,code,codeRegion"
URL_REGIONS = "https://geo.api.gouv.fr/regions?fields=nom,code"


def charger(client) -> dict[str, dict]:
    """{code_departement: {"region": code_region, "region_nom": nom_region}}."""
    departements = client.get_json(URL_DEPARTEMENTS)
    regions = {r["code"]: r["nom"] for r in client.get_json(URL_REGIONS)
               if isinstance(r, dict) and r.get("code") and r.get("nom")}
    if not isinstance(departements, list) or not regions:
        raise ValueError("Réponse de geo.api.gouv.fr inattendue (départements ou régions)")
    resultat = {}
    for d in departements:
        code, region = d.get("code"), d.get("codeRegion")
        if code and region in regions:
            resultat[code] = {"region": region, "region_nom": regions[region]}
    return resultat
