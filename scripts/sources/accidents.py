"""Accidents de vélo : jeu « Accidents de vélo » d'Opendatasoft/Koumoul (data-fair),
construit à partir des fichiers BAAC de l'ONISR (Licence Ouverte).

Récupération : API data-fair /lines en JSON, par pages de 10 000 lignes, en ne demandant
que les colonnes utiles (≈ 8 requêtes, ≈ 10 Mo). Plus simple et plus sûr que l'export CSV :
types JSON, pas de séparateur ni d'encodage à deviner.

Unités :
  - une LIGNE de la source = un CYCLISTE impliqué (victime ou indemne) ;
  - un ACCIDENT = un identifiant Num_Acc distinct ;
  - gravité d'un accident = gravité du cycliste le plus gravement atteint.

Codes BAAC (documentation ONISR « Description des bases de données annuelles ») :
  grav   1 indemne, 2 tué, 3 blessé hospitalisé, 4 blessé léger, -1 non renseigné
  trajet 1 domicile-travail, 2 domicile-école, 3 courses, 4 professionnel, 5 promenade-loisirs,
         9 autre ; 0 et -1 = non renseigné (0 est utilisé ainsi avant 2019)
  situ   1 chaussée, 2 bande d'arrêt d'urgence, 3 accotement, 4 trottoir, 5 piste cyclable,
         6 autre voie spéciale et 8 autres (codes créés en 2019) ; 0 et -1 = non renseigné
  typevehicules : catv des AUTRES véhicules, éventuellement plusieurs (« 7 / 18 »)
  obsm   obstacle mobile heurté ; 1 = piéton
"""

from __future__ import annotations

from collections import defaultdict

from sources.communes import commune_entiere, departement_du_code

URL_JEU = "https://opendata.koumoul.com/data-fair/api/v1/datasets/accidents-velos"
URL_PAGE_JEU = "https://opendata.koumoul.com/datasets/accidents-velos"
CHAMPS = "Num_Acc,an,dep,com,grav,trajet,situ,typevehicules,numVehicules,obsm"
URL_LIGNES = f"{URL_JEU}/lines?size=10000&select={CHAMPS}&sort=_i"

# --- Libellés harmonisés (l'ordre fixe l'indice utilisé dans les fichiers publiés) ---

GRAVITES = ["Mortel", "Grave (blessé hospitalisé)", "Léger", "Sans blessé", "Gravité non renseignée"]
G_MORTEL, G_GRAVE, G_LEGER, G_INDEMNE, G_NR = range(5)
RANG_GRAV = {"2": G_MORTEL, "3": G_GRAVE, "4": G_LEGER, "1": G_INDEMNE}  # plus petit = plus grave

VEHICULES = ["Voiture", "Utilitaire", "Poids lourd", "Bus, car, tram ou train", "Deux-roues motorisé",
             "Autre vélo", "Trottinette ou autre EDP", "Piéton", "Aucun autre usager", "Autre ou indéterminé"]
# catv -> groupe ; l'ordre de priorité (le « plus lourd » l'emporte) est celui de la liste ci-dessus
CATV_GROUPE = {}
for _codes, _g in [((3, 7, 8, 9), 0), ((10, 12), 1), ((13, 14, 15, 16, 17), 2), ((18, 19, 37, 38, 39, 40), 3),
                   ((2, 4, 5, 6, 30, 31, 32, 33, 34, 35, 36, 41, 42, 43), 4), ((1, 80), 5), ((50, 60), 6),
                   ((0, 11, 20, 21, 99), 9)]:
    for _c in _codes:
        CATV_GROUPE[_c] = _g
V_PIETON, V_AUCUN, V_AUTRE = 7, 8, 9
PRIORITE_VEH = [2, 3, 1, 0, 4, 5, 6, 9]  # poids lourd d'abord, « autre » en dernier

TRAJETS = ["Domicile – travail", "Domicile – école", "Courses – achats", "Utilisation professionnelle",
           "Promenade – loisirs", "Autre motif", "Non renseigné"]
CODE_TRAJET = {"1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "9": 5}

SITUATIONS = ["Sur chaussée", "Sur piste cyclable", "Sur trottoir", "Sur accotement",
              "Sur bande d'arrêt d'urgence", "Sur autre voie spéciale", "Autre situation", "Non renseignée"]
CODE_SITU = {"1": 0, "5": 1, "4": 2, "3": 3, "2": 4, "6": 5, "8": 6}

# Ruptures de série affichées sur le site
RUPTURES = [
    {"annees": [2018, None], "texte": "À partir de 2018, cette base compte nettement moins de cyclistes que "
     "les bilans officiels de l'ONISR (par exemple 156 tués en 2023 contre 226). Elle semble ne pas inclure "
     "les vélos à assistance électrique, codés à part depuis 2018. Les années 2018 et suivantes ne sont donc "
     "pas comparables aux précédentes, et les chiffres récents sont sous-estimés."},
    {"annees": [2019, None], "texte": "Depuis 2019, l'ONISR ne labellise plus l'indicateur « blessé "
     "hospitalisé » comme statistique publique : la donnée existe toujours mais doit être lue avec prudence."},
    {"annees": [2019, None], "texte": "Les situations « autre voie spéciale » et « autre » n'existent que "
     "depuis la refonte des fichiers en 2019. Avant 2019, le code 0 servait aussi pour « non renseigné »."},
]


def _txt(v) -> str:
    return "" if v is None else str(v).strip()


def normaliser_lieu(dep_brut, com_brut) -> tuple[str | None, str | None]:
    """(département, commune) au format INSEE actuel.

    - départements sans zéro initial (« 1 » -> « 01 ») dans certaines années ;
    - Paris avant 2010 : « 750NN » au lieu de « 751NN » (NN = arrondissement) ;
    - le département est déduit du code commune quand il est valide.
    """
    com = _txt(com_brut).upper()
    if len(com) == 4 and com.isdigit():
        com = "0" + com
    if len(com) == 5 and com.startswith("750") and com[3:].isdigit() and 1 <= int(com[3:]) <= 20:
        com = "751" + com[3:]
    if len(com) == 5 and (com.isdigit() or com[:2] in ("2A", "2B")):
        return departement_du_code(com), com
    dep = _txt(dep_brut).upper()
    if dep.isdigit() and len(dep) == 1:
        dep = "0" + dep
    return (dep or None), None


def groupes_vehicules(typevehicules) -> list[int]:
    groupes = []
    for morceau in _txt(typevehicules).replace(",", "/").split("/"):
        morceau = morceau.strip()
        if morceau.lstrip("-").isdigit():
            groupes.append(CATV_GROUPE.get(int(morceau), V_AUTRE))
    return groupes


def lire_lignes(client):
    """Itère sur toutes les lignes de la source (pagination data-fair par « next »)."""
    url, pages, lues, total = URL_LIGNES, 0, 0, None
    while url:
        page = client.get_json(url)
        pages += 1
        total = page.get("total", total)
        resultats = page.get("results") or []
        for ligne in resultats:
            lues += 1
            yield ligne
        url = page.get("next") if resultats else None
        if pages > 200:
            raise ValueError("Pagination anormalement longue")
    # Garde-fou : ne jamais publier une série tronquée sans le savoir
    if isinstance(total, int) and lues < total:
        raise ValueError(f"Lecture incomplète : {lues} lignes sur {total} annoncées")


def construire_accidents(lignes, codes_valides: set[str], correspondance=None) -> dict:
    """Regroupe les lignes (cyclistes) en accidents.

    Renvoie {"accidents": [...], "stats": {...}} ; chaque accident est un dict
    {an, dep, com, g, v, t, s, tues, hosp, legers, indemnes, nr}.
    """
    par_acc: dict[str, dict] = {}
    stats = defaultdict(int)
    for l in lignes:
        stats["lignes"] += 1
        num = _txt(l.get("Num_Acc"))
        an = l.get("an")
        if not num or not isinstance(an, int):
            stats["lignes_sans_identifiant_ou_annee"] += 1
            continue
        dep, com = normaliser_lieu(l.get("dep"), l.get("com"))
        if dep not in codes_valides:
            stats["lignes_hors_metropole"] += 1
            continue
        a = par_acc.get(num)
        if a is None:
            a = par_acc[num] = {"an": an, "dep": dep, "com": com, "g": G_NR, "v": None, "t": 6, "s": 7,
                                "tues": 0, "hosp": 0, "legers": 0, "indemnes": 0, "nr": 0,
                                "_vehs": set(), "_pieton": False, "_rang_t": 99}
            situ = CODE_SITU.get(_txt(l.get("situ")))
            if situ is not None:
                a["s"] = situ
        grav = _txt(l.get("grav"))
        rang = RANG_GRAV.get(grav, G_NR)
        cle = {G_MORTEL: "tues", G_GRAVE: "hosp", G_LEGER: "legers", G_INDEMNE: "indemnes"}.get(rang, "nr")
        a[cle] += 1
        if rang < a["g"]:
            a["g"] = rang
        # Motif : celui du cycliste le plus gravement atteint (à défaut, le premier renseigné)
        trajet = CODE_TRAJET.get(_txt(l.get("trajet")))
        if trajet is not None and rang < a["_rang_t"]:
            a["t"], a["_rang_t"] = trajet, rang
        a["_vehs"].update(groupes_vehicules(l.get("typevehicules")))
        if _txt(l.get("obsm")) == "1":
            a["_pieton"] = True

    accidents = []
    for a in par_acc.values():
        vehs = a.pop("_vehs")
        pieton = a.pop("_pieton")
        a.pop("_rang_t")
        if vehs:
            a["v"] = next(g for g in PRIORITE_VEH if g in vehs)
        else:
            a["v"] = V_PIETON if pieton else V_AUCUN
        if a["com"] and correspondance is not None and correspondance.resoudre(a["com"]) is None:
            stats["accidents_commune_inconnue"] += 1
        accidents.append(a)
    stats["accidents"] = len(accidents)
    if not accidents:
        raise ValueError("Aucun accident lu dans la source")
    accidents.sort(key=lambda a: (a["an"], a["dep"], a["com"] or ""))
    return {"accidents": accidents, "stats": dict(stats)}


# --------------------------------------------------------------------------
# Agrégation par zone (France, région, département)
# --------------------------------------------------------------------------

def zone_vide(n_annees: int) -> dict:
    z = lambda: [0] * n_annees  # noqa: E731
    return {"acc": z(), "tues": z(), "hosp": z(), "legers": z(), "indemnes": z(), "nr": z(),
            "grav": [[0] * len(GRAVITES) for _ in range(n_annees)],
            "veh": [[[0] * len(GRAVITES) for _ in VEHICULES] for _ in range(n_annees)],
            "traj": [[0] * len(TRAJETS) for _ in range(n_annees)],
            "situ": [[[0] * len(GRAVITES) for _ in SITUATIONS] for _ in range(n_annees)]}


def ajouter(zone: dict, a: dict, i: int) -> None:
    zone["acc"][i] += 1
    for cle in ("tues", "hosp", "legers", "indemnes", "nr"):
        zone[cle][i] += a[cle]
    zone["grav"][i][a["g"]] += 1
    zone["veh"][i][a["v"]][a["g"]] += 1
    zone["traj"][i][a["t"]] += 1
    zone["situ"][i][a["s"]][a["g"]] += 1


def agreger(accidents: list[dict], region_de: dict[str, str]) -> dict:
    annees = list(range(min(a["an"] for a in accidents), max(a["an"] for a in accidents) + 1))
    idx = {an: i for i, an in enumerate(annees)}
    zones: dict[str, dict] = defaultdict(lambda: zone_vide(len(annees)))
    for a in accidents:
        i = idx[a["an"]]
        ajouter(zones["FR"], a, i)
        ajouter(zones["D" + a["dep"]], a, i)
        if region_de.get(a["dep"]):
            ajouter(zones["R" + region_de[a["dep"]]], a, i)
    return {"annees": annees, "zones": dict(zones)}


def compter_par_commune(accidents: list[dict], correspondance, annees: list[int]) -> dict[str, dict]:
    """{commune_entiere: {"acc": [par an], "tues": [par an], "blesses": [par an]}}."""
    idx = {an: i for i, an in enumerate(annees)}
    res: dict[str, dict] = {}
    for a in accidents:
        com = correspondance.resoudre(a["com"]) if correspondance else commune_entiere(a["com"])
        if not com:
            continue
        r = res.setdefault(com, {"acc": [0] * len(annees), "tues": [0] * len(annees),
                                 "blesses": [0] * len(annees)})
        i = idx[a["an"]]
        r["acc"][i] += 1
        r["tues"][i] += a["tues"]
        r["blesses"][i] += a["hosp"] + a["legers"]
    return res


def enregistrement(a: dict, correspondance=None) -> list:
    """Forme compacte publiée par département : une liste par accident.

    com = commune actuelle entière (anciennes communes rattachées, Paris/Lyon/Marseille
    regroupés), vide si inconnue ; arr = arrondissement municipal d'origine, sinon vide.
    """
    com = correspondance.resoudre(a["com"]) if correspondance else commune_entiere(a["com"])
    arr = a["com"] if a["com"] and commune_entiere(a["com"]) != a["com"] else ""
    return [a["an"], com or "", arr, a["g"], a["v"], a["t"], a["s"],
            a["tues"], a["hosp"], a["legers"], a["indemnes"], a["nr"]]


CHAMPS_ENREGISTREMENT = ["an", "com", "arr", "gravite", "vehicule", "trajet", "situ",
                         "tues", "hosp", "legers", "indemnes", "gravite_nr"]


def metadonnees(client) -> dict:
    """Date de mise à jour et nombre de lignes annoncés par la source."""
    try:
        m = client.get_json(URL_JEU)
        return {"maj": (m.get("dataUpdatedAt") or m.get("updatedAt") or "")[:10] or None,
                "lignes": m.get("count")}
    except Exception:
        return {"maj": None, "lignes": None}
