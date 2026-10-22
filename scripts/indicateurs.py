"""Calcul des indicateurs, des rangs nationaux et du score vélo.

Le score vélo (0 à 100) est la moyenne des rangs centiles du département sur
les indicateurs de SCORE_INDICATEURS. Un rang centile de 100 signifie « meilleur
département de France sur cet indicateur », 0 « dernier ». En cas d'égalité,
les départements concernés reçoivent la moyenne de leurs rangs.
"""

from __future__ import annotations

# Description des indicateurs, utilisée aussi par le site (via meta.json).
# sens = 1 : plus c'est grand, mieux c'est.
INDICATEURS = [
    {"cle": "score", "libelle": "Score vélo", "unite": "/ 100", "decimales": 0, "groupe": "Synthèse"},
    {"cle": "km_total", "libelle": "Aménagements cyclables (total)", "unite": "km", "decimales": 0, "groupe": "Aménagements"},
    {"cle": "km_10k_hab", "libelle": "Aménagements pour 10 000 habitants", "unite": "km / 10 000 hab.", "decimales": 1, "groupe": "Aménagements"},
    {"cle": "km_par_km2", "libelle": "Densité d'aménagements", "unite": "km / km²", "decimales": 2, "groupe": "Aménagements"},
    {"cle": "km_pistes", "libelle": "Pistes cyclables", "unite": "km", "decimales": 0, "groupe": "Aménagements par type"},
    {"cle": "km_bandes", "libelle": "Bandes cyclables", "unite": "km", "decimales": 0, "groupe": "Aménagements par type"},
    {"cle": "km_voies_vertes", "libelle": "Voies vertes", "unite": "km", "decimales": 0, "groupe": "Aménagements par type"},
    {"cle": "km_double_sens", "libelle": "Double-sens cyclables", "unite": "km", "decimales": 0, "groupe": "Aménagements par type"},
    {"cle": "km_autres", "libelle": "Autres aménagements", "unite": "km", "decimales": 0, "groupe": "Aménagements par type"},
    {"cle": "vls_stations", "libelle": "Stations de vélos en libre-service", "unite": "stations", "decimales": 0, "groupe": "Vélos en libre-service"},
    {"cle": "vls_velos", "libelle": "Vélos en libre-service disponibles", "unite": "vélos", "decimales": 0, "groupe": "Vélos en libre-service"},
    {"cle": "vls_stations_100k", "libelle": "Stations pour 100 000 habitants", "unite": "stations / 100 000 hab.", "decimales": 1, "groupe": "Vélos en libre-service"},
    {"cle": "stat_places", "libelle": "Places de stationnement vélo", "unite": "places", "decimales": 0, "groupe": "Stationnement"},
    {"cle": "stat_places_secu", "libelle": "Places sécurisées (accroche cadre)", "unite": "places", "decimales": 0, "groupe": "Stationnement"},
    {"cle": "stat_secu_1000", "libelle": "Places sécurisées pour 1 000 habitants", "unite": "places / 1 000 hab.", "decimales": 1, "groupe": "Stationnement"},
]

SCORE_INDICATEURS = ["km_total", "km_10k_hab", "km_par_km2",
                     "vls_stations", "vls_velos", "vls_stations_100k"]


def ratio(numerateur, denominateur, facteur: float = 1.0):
    """numérateur / dénominateur × facteur, ou None si une donnée manque."""
    if numerateur is None or not denominateur:
        return None
    return numerateur / denominateur * facteur


def rangs_centiles(valeurs: dict[str, float | None]) -> dict[str, float | None]:
    """{code: valeur} -> {code: rang centile 0–100}, égalités = rang moyen."""
    connus = sorted((v, k) for k, v in valeurs.items() if v is not None)
    n = len(connus)
    resultat: dict[str, float | None] = {k: None for k in valeurs}
    if n == 0:
        return resultat
    if n == 1:
        resultat[connus[0][1]] = 100.0
        return resultat
    i = 0
    while i < n:
        j = i
        while j + 1 < n and connus[j + 1][0] == connus[i][0]:
            j += 1
        rang_moyen = (i + j) / 2  # rangs 0..n-1
        for _, k in connus[i:j + 1]:
            resultat[k] = rang_moyen / (n - 1) * 100
        i = j + 1
    return resultat


def rangs_nationaux(valeurs: dict[str, float | None]) -> dict[str, int | None]:
    """{code: rang} avec 1 = valeur la plus élevée ; ex æquo = même rang."""
    connues = [v for v in valeurs.values() if v is not None]
    return {k: (None if v is None else 1 + sum(1 for w in connues if w > v))
            for k, v in valeurs.items()}


def calculer(departements: list[dict]) -> list[dict]:
    """Complète chaque département (dict de propriétés) avec ratios, score et rangs."""
    for d in departements:
        km, pop, surf = d.get("km_total"), d.get("population"), d.get("surface_km2")
        d["km_10k_hab"] = ratio(km, pop, 10_000)
        d["km_par_km2"] = ratio(km, surf)
        d["vls_stations_100k"] = ratio(d.get("vls_stations"), pop, 100_000)

    centiles = {cle: rangs_centiles({d["code"]: d.get(cle) for d in departements})
                for cle in SCORE_INDICATEURS}
    for d in departements:
        notes = [centiles[cle][d["code"]] for cle in SCORE_INDICATEURS
                 if centiles[cle][d["code"]] is not None]
        d["score"] = sum(notes) / len(notes) if notes else None
        d["score_nb_indicateurs"] = len(notes)

    # Arrondi à 6 chiffres significatifs : fichier léger, précision largement suffisante
    for d in departements:
        for ind in INDICATEURS:
            v = d.get(ind["cle"])
            if v is not None:
                d[ind["cle"]] = float(f"{v:.6g}") if isinstance(v, float) else v

    for ind in INDICATEURS:
        rangs = rangs_nationaux({d["code"]: d.get(ind["cle"]) for d in departements})
        for d in departements:
            d.setdefault("rangs", {})[ind["cle"]] = rangs[d["code"]]
    return departements
