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


def calculer_communes(fiches: dict[str, dict], seuil_population: int) -> dict:
    """Indicateurs et score vélo des communes d'au moins `seuil_population` habitants.

    fiches : {code: fiche publiée dans communes/{dep}.json, plus "d" (département)}.
    Le score suit la même méthode que celui des départements (moyenne des rangs centiles des
    6 indicateurs de SCORE_INDICATEURS), mais calculée entre ces communes seulement : les très
    petites communes, où un seul kilomètre change tout, en sont écartées.
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
    centiles = {cle: rangs_centiles({c: d.get(cle) for c, d in lignes.items()}) for cle in SCORE_INDICATEURS}
    for c, d in lignes.items():
        notes = [centiles[cle][c] for cle in SCORE_INDICATEURS if centiles[cle][c] is not None]
        # Score seulement si les 6 indicateurs sont connus (sinon la comparaison serait faussée)
        d["score"] = sum(notes) / len(notes) if len(notes) == len(SCORE_INDICATEURS) else None
    champs = ["code", "nom", "dep", "pop"] + INDICATEURS_COMMUNES
    sortie = []
    for c, d in lignes.items():
        vals = [None if d.get(k) is None else (float(f"{d[k]:.6g}") if isinstance(d[k], float) else d[k])
                for k in INDICATEURS_COMMUNES]
        sortie.append([c, fiches[c].get("n"), fiches[c].get("d"), fiches[c].get("p")] + vals)
    return {"seuil_population": seuil_population, "champs": champs, "lignes": sortie}


# --------------------------------------------------------------------------
# Score vélo « simplifié » (carte d'accueil). Nom interne : score_simple, pour ne pas le confondre
# avec le score vélo complet de la carte détaillée ; sur le site, les deux s'appellent « score vélo ».
# --------------------------------------------------------------------------
# Il ne repose que sur les deux données montrées sur la carte d'accueil, rapportées à la population
# pour comparer des territoires de tailles différentes :
#   - km d'aménagements cyclables pour 10 000 habitants ;
#   - stations de vélos en libre-service pour 100 000 habitants (vraies stations, sans les zones
#     virtuelles du free-floating).
# Méthode identique au score complet : rang centile (0 à 100) sur chaque ratio, puis moyenne.
# Pour les communes, la population retenue au dénominateur est d'au moins PLANCHER_POPULATION
# habitants (même seuil que les classements et corrélations du site) : sinon un hameau traversé par
# une voie verte, ou doté d'une seule station, passerait devant les grandes villes cyclables
# (1 km pour 30 habitants = 333 km pour 10 000 habitants). Mesuré sur les vraies données : avec un
# plancher de 2 000 habitants, le haut du classement restait occupé par des villages dotés d'une
# seule station (95 % des communes n'en ont aucune) ; avec 10 000, ce sont des villes et des bourgs
# bien équipés, et les grandes villes cyclables remontent.

SCORE_SIMPLE_INDICATEURS = ["km_10k_hab", "vls_stations_100k"]
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


def _score_simple(ratios: dict[str, dict[str, float | None]]) -> dict[str, float | None]:
    """ratios : {code: {"km_10k_hab": x, "vls_stations_100k": y}} -> {code: score sur 100}.
    Score seulement si les deux ratios sont connus (une commune sans donnée n'est pas classée)."""
    centiles = {cle: rangs_centiles({c: r.get(cle) for c, r in ratios.items()}) for cle in SCORE_SIMPLE_INDICATEURS}
    res = {}
    for c in ratios:
        notes = [centiles[cle][c] for cle in SCORE_SIMPLE_INDICATEURS]
        res[c] = None if any(n is None for n in notes) else round(sum(notes) / len(notes), 4)
    return res


def score_simple_departements(departements: list[dict]) -> None:
    """Ajoute score_simple et rang_score_simple (+ ex æquo) aux propriétés des départements."""
    ratios = {d["code"]: {"km_10k_hab": d.get("km_10k_hab"), "vls_stations_100k": d.get("vls_stations_100k")}
              for d in departements}
    scores = _score_simple(ratios)
    rangs = rangs_rapides(scores)
    for d in departements:
        d["score_simple"] = None if scores[d["code"]] is None else float(f"{scores[d['code']]:.6g}")
        r = rangs[d["code"]]
        d["rang_score_simple"] = r[0] if r else None
        d["ex_aequo_score_simple"] = bool(r and r[1] > 1)
    d0 = [d for d in departements if d["score_simple"] is not None]
    for d in departements:
        d["nb_classes_score_simple"] = len(d0)


def score_simple_communes(fiches: dict[str, dict]) -> dict:
    """fiches : {code: {"p": population, "km": {"t": km}, "vls": {"st": stations}}}.

    Renvoie {"sur": nombre de communes classées, "communes": {code: [score, rang, nb_ex_aequo]}}.
    Une commune sans population, sans km connu ou sans donnée VLS n'est pas classée.
    """
    ratios = {}
    for code, f in fiches.items():
        pop, km, vls = f.get("p"), (f.get("km") or {}).get("t"), f.get("vls")
        if not pop or km is None or vls is None:
            continue
        base = max(pop, PLANCHER_POPULATION)
        ratios[code] = {"km_10k_hab": km / base * 10_000, "vls_stations_100k": vls.get("st", 0) / base * 100_000}
    scores = _score_simple(ratios)
    rangs = rangs_rapides(scores)
    res = {c: [round(scores[c], 1), rangs[c][0], rangs[c][1]] for c in scores if scores[c] is not None}
    return {"sur": len(res), "communes": res}
