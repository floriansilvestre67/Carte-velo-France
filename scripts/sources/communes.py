"""Population et surface des communes (geo.api.gouv.fr), agrégées par département."""

from __future__ import annotations

URL_COMMUNES = "https://geo.api.gouv.fr/communes?fields=code,population,surface,codeDepartement"


def charger_communes(client) -> list[dict]:
    donnees = client.get_json(URL_COMMUNES)
    if not isinstance(donnees, list) or len(donnees) < 1000:
        raise ValueError("Réponse de geo.api.gouv.fr inattendue (liste de communes trop courte)")
    return donnees


def agreger_par_departement(communes: list[dict]) -> dict[str, dict]:
    """{code_dep: {population, surface_km2}}.

    La surface fournie par l'API est en hectares : on la convertit en km² (÷ 100).
    Une commune sans population ou sans surface est simplement ignorée pour ce champ.
    """
    resultat: dict[str, dict] = {}
    for c in communes:
        dep = c.get("codeDepartement")
        if not dep:
            continue
        r = resultat.setdefault(dep, {"population": 0, "surface_km2": 0.0})
        if isinstance(c.get("population"), (int, float)):
            r["population"] += c["population"]
        if isinstance(c.get("surface"), (int, float)):
            r["surface_km2"] += c["surface"] / 100.0
    return resultat


def correspondance_commune_departement(communes: list[dict]) -> dict[str, str]:
    """{code_insee_commune: code_departement}, utile pour les codes ambigus."""
    return {c["code"]: c["codeDepartement"] for c in communes
            if c.get("code") and c.get("codeDepartement")}
