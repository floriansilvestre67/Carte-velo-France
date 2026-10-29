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


# --------------------------------------------------------------------------
# Classement des communes (panneau « Les 10 premières communes » de la carte)
# --------------------------------------------------------------------------

# Indicateurs calculables à l'échelle d'une commune (les autres n'existent qu'au niveau départemental)
INDICATEURS_COMMUNES = ["score", "km_total", "km_10k_hab", "km_par_km2", "km_pistes", "km_bandes",
                        "km_voies_vertes", "km_double_sens", "km_autres", "vls_stations", "vls_velos",
                        "vls_stations_100k", "stat_places", "stat_places_secu", "stat_secu_1000"]


def calculer_communes(fiches: dict[str, dict], seuil_population: int, scores_nationaux: dict) -> dict:
    """Indicateurs des communes d'au moins `seuil_population` habitants (onglet « 10 premières communes »).

    fiches : {code: fiche publiée dans communes/{dep}.json, plus "d" (département)}.
    scores_nationaux : {code: [score, rang, ex æquo]} calculés par score_communes entre toutes les
    communes, pour que chaque commune ait le même score sur les deux cartes.
    Les stations VLS sont les vraies stations (les zones virtuelles du free-floating ne comptent pas).
    """
    lignes = {}
    for code, f in fiches.items():
        pop = f.get("p")
        if not pop or pop < seuil_population:
            continue
        km = f.get("km") or {}
        vls, stat = f.get("vls"), f.get("stat") or {}
        d = {"km_total": km.get("t"), "vls_stations": vls.get("st") if vls else None,
             "vls_velos": vls.get("v") if vls else None,
             "stat_places": stat.get("p"), "stat_places_secu": stat.get("s"), "stat_secu_1000": stat.get("s1000")}
        for cat in ("pistes", "bandes", "voies_vertes", "double_sens", "autres"):
            d["km_" + cat] = km.get(cat, 0) if km else None
        d["km_10k_hab"] = ratio(d["km_total"], pop, 10_000)
        d["km_par_km2"] = ratio(d["km_total"], f.get("s"))
        d["vls_stations_100k"] = ratio(d["vls_stations"], pop, 100_000)
        lignes[code] = d
    # Score : celui de toutes les communes (score_communes), le même que sur la carte d'accueil
    for c, d in lignes.items():
        d["score"] = (scores_nationaux.get(c) or [None])[0]
    champs = ["code", "nom", "dep", "pop"] + INDICATEURS_COMMUNES
    sortie = []
    for c, d in lignes.items():
        vals = [None if d.get(k) is None else (float(f"{d[k]:.6g}") if isinstance(d[k], float) else d[k])
                for k in INDICATEURS_COMMUNES]
        sortie.append([c, fiches[c].get("n"), fiches[c].get("d"), fiches[c].get("p")] + vals)
    return {"seuil_population": seuil_population, "champs": champs, "lignes": sortie}


# --------------------------------------------------------------------------
# Score vélo des communes (même score sur la carte d'accueil et sur la carte détaillée)
# --------------------------------------------------------------------------
# Même méthode et mêmes six indicateurs que pour les départements (SCORE_INDICATEURS), calculés
# entre toutes les communes de métropole. Pour les deux ratios par habitant, la population retenue
# est d'au moins PLANCHER_POPULATION habitants (le seuil déjà utilisé par les classements du site) :
# sinon un hameau traversé par une voie verte ou doté d'une seule station passerait devant les
# grandes villes cyclables (1 km pour 30 habitants = 333 km pour 10 000 habitants).

PLANCHER_POPULATION = 10_000


def rangs_rapides(valeurs: dict[str, float | None]) -> dict[str, tuple[int, int] | None]:
    """{code: (rang, nombre d'ex æquo)} avec 1 = valeur la plus élevée ; tri en O(n log n)."""
    connues = sorted((v for v in valeurs.values() if v is not None), reverse=True)
    premier: dict[float, int] = {}
    effectif: dict[float, int] = {}
    for i, v in enumerate(connues):
        premier.setdefault(v, i + 1)
        effectif[v] = effectif.get(v, 0) + 1
    return {k: (None if v is None else (premier[v], effectif[v])) for k, v in valeurs.items()}


def indicateurs_score_commune(f: dict) -> dict[str, float | None] | None:
    """Les six indicateurs du score pour une fiche commune, ou None s'il en manque un."""
    pop, km, vls, surf = f.get("p"), (f.get("km") or {}).get("t"), f.get("vls"), f.get("s")
    if not pop or km is None or vls is None or not surf:
        return None
    base = max(pop, PLANCHER_POPULATION)
    return {"km_total": km, "km_10k_hab": km / base * 10_000, "km_par_km2": km / surf,
            "vls_stations": vls.get("st", 0), "vls_velos": vls.get("v", 0),
            "vls_stations_100k": vls.get("st", 0) / base * 100_000}


def score_communes(fiches: dict[str, dict]) -> dict:
    """Score vélo de toutes les communes, avec rang national et ex æquo.

    Renvoie {"sur": nombre de communes classées, "communes": {code: [score, rang, nb_ex_aequo]}}.
    Une commune dont il manque une donnée (population, surface, km ou vélos en libre-service)
    n'est pas classée.
    """
    ind = {c: v for c, v in ((c, indicateurs_score_commune(f)) for c, f in fiches.items()) if v}
    centiles = {cle: rangs_centiles({c: v[cle] for c, v in ind.items()}) for cle in SCORE_INDICATEURS}
    scores = {c: round(sum(centiles[cle][c] for cle in SCORE_INDICATEURS) / len(SCORE_INDICATEURS), 4) for c in ind}
    rangs = rangs_rapides(scores)
    return {"sur": len(scores), "communes": {c: [round(scores[c], 1), rangs[c][0], rangs[c][1]] for c in scores}}
