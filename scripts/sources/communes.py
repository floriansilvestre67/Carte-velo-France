"""Communes (geo.api.gouv.fr) : population, surface, nom, et correspondance des codes.

Deux usages :
  - agréger population et surface par département ;
  - ramener n'importe quel code commune rencontré dans les sources (arrondissement de
    Paris/Lyon/Marseille, ancienne commune fusionnée) à la commune actuelle entière.
"""

from __future__ import annotations

URL_COMMUNES = "https://geo.api.gouv.fr/communes?fields=nom,code,codesPostaux,population,surface,codeDepartement"
URL_ARRONDISSEMENTS = ("https://geo.api.gouv.fr/communes?type=arrondissement-municipal"
                       "&fields=nom,code,codesPostaux,population,codeDepartement")
# Communes déléguées et associées : anciennes communes rattachées à une commune nouvelle.
URL_DELEGUEES = "https://geo.api.gouv.fr/communes?type=commune-deleguee&fields=code,nom,chefLieu"
URL_ASSOCIEES = "https://geo.api.gouv.fr/communes?type=commune-associee&fields=code,nom,chefLieu"

# Arrondissements municipaux -> commune entière
PLM = {"75": ("751", 1, 20, "75056"), "69": ("6938", 1, 9, "69123"), "13": ("132", 1, 16, "13055")}


def charger_communes(client) -> list[dict]:
    donnees = client.get_json(URL_COMMUNES)
    if not isinstance(donnees, list) or len(donnees) < 1000:
        raise ValueError("Réponse de geo.api.gouv.fr inattendue (liste de communes trop courte)")
    return donnees


def charger_anciennes(client) -> dict[str, str]:
    """{code_ancienne_commune: code_commune_actuelle}. Facultatif : vide en cas d'échec."""
    table: dict[str, str] = {}
    for url in (URL_DELEGUEES, URL_ASSOCIEES):
        try:
            for c in client.get_json(url) or []:
                if isinstance(c, dict) and c.get("code") and c.get("chefLieu") and c["code"] != c["chefLieu"]:
                    table[c["code"]] = c["chefLieu"]
        except Exception:
            continue
    return table


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


def commune_entiere(code: str | None) -> str | None:
    """75108 -> 75056 (Paris), 69383 -> 69123 (Lyon), 13205 -> 13055 (Marseille) ; sinon inchangé."""
    if not code or len(code) != 5:
        return code
    regle = PLM.get(code[:2])
    if regle:
        prefixe, debut, fin, entiere = regle
        suffixe = code[len(prefixe):]
        if code.startswith(prefixe) and suffixe.isdigit() and debut <= int(suffixe) <= fin:
            return entiere
    return code


def departement_du_code(code: str) -> str:
    if code[:2] in ("2A", "2B"):
        return code[:2]
    return code[:3] if code.startswith("97") else code[:2]


class Correspondance:
    """Ramène un code commune quelconque à la commune actuelle entière, avec son département."""

    def __init__(self, communes: list[dict], anciennes: dict[str, str] | None = None):
        self.actuelles = {c["code"]: c for c in communes if c.get("code")}
        self.anciennes = anciennes or {}

    def resoudre(self, code) -> str | None:
        """Code de la commune actuelle entière, ou None si le code est inconnu."""
        if not code:
            return None
        code = commune_entiere(str(code).strip().upper().zfill(5))
        if code in self.actuelles:
            return code
        if code in self.anciennes:
            return commune_entiere(self.anciennes[code])
        return None

    def departement(self, code) -> str | None:
        actuelle = self.resoudre(code)
        if actuelle:
            return self.actuelles[actuelle].get("codeDepartement") or departement_du_code(actuelle)
        return departement_du_code(str(code).strip().upper().zfill(5)) if code else None


def index_recherche(communes: list[dict], arrondissements: list[dict], codes_valides: set[str]) -> dict:
    """Liste compacte pour la recherche de ville : nom, codes postaux, population.

    Les arrondissements de Paris, Lyon et Marseille y figurent aussi, rattachés à leur
    commune entière (taper « Paris » propose Paris ; « 75008 » propose le 8e arrondissement).
    """
    lignes = []
    for c in communes:
        if c.get("codeDepartement") in codes_valides and c.get("code"):
            lignes.append([c["code"], c.get("nom") or c["code"], " ".join(c.get("codesPostaux") or []),
                           c.get("population") or 0, ""])
    for a in arrondissements:
        if a.get("codeDepartement") in codes_valides and a.get("code"):
            lignes.append([a["code"], a.get("nom") or a["code"], " ".join(a.get("codesPostaux") or []),
                           a.get("population") or 0, commune_entiere(a["code"])])
    lignes.sort(key=lambda l: -l[3])
    return {"champs": ["code", "nom", "codes_postaux", "population", "commune_entiere"], "communes": lignes}
