"""Fichiers annuels des accidents corporels (BAAC) de l'ONISR, publiés sur data.gouv.fr.

Jeu « Bases de données annuelles des accidents corporels de la circulation routière »
(ministère de l'Intérieur, Licence Ouverte), lu via l'API data.gouv.fr à partir de son
identifiant : une nouvelle année (2025…) est prise en compte dès sa publication, même si
le nom du jeu change.

Chaque année compte quatre tables, reliées par l'identifiant d'accident :
  caractéristiques  date, département, commune
  lieux             situation de l'accident (chaussée, piste cyclable…)
  véhicules         catégorie de chaque véhicule (catv : 01 bicyclette, 80 vélo à assistance électrique)
  usagers           chaque personne impliquée : véhicule, catégorie (conducteur, passager, piéton),
                    gravité, motif du déplacement

Formats : deux générations de fichiers.
  - 2005–2018 : séparateur virgule (tabulation en 2009), encodage Windows-1252, département
    sur 3 caractères (« 590 » pour le Nord, « 201 »/« 202 » pour la Corse), commune sur 3 chiffres ;
  - depuis 2019 : séparateur point-virgule, UTF-8, département et code INSEE complets ;
    en 2022 l'identifiant s'appelle « Accident_Id » dans le fichier des caractéristiques.
On ne retient que les accidents impliquant au moins un vélo ou un VAE ; pour chacun, une
ligne par cycliste (conducteur ou passager d'un vélo), au même format que le reste du
traitement (voir accidents.construire_accidents).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from pathlib import Path

ID_JEU = "53698f4ca3a729239d2036df"
URL_API = f"https://www.data.gouv.fr/api/1/datasets/{ID_JEU}/"
URL_PAGE = ("https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-"
            "de-la-circulation-routiere-annees-de-2005-a-2024/")
URL_DOC = ("https://static.data.gouv.fr/resources/bases-de-donnees-annuelles-des-accidents-corporels-de-la-"
           "circulation-routiere-annees-de-2005-a-2024/20251021-115933/description-des-bases-de-donnees-annuelles.pdf")
VERSION = 2   # à augmenter si le traitement change : force un nouveau calcul
              # (2 : type de vélo du cycliste, classique ou à assistance électrique)

CATV_VELO = {1, 80}
CATV_VAE = 80      # vélo à assistance électrique, catégorie distincte depuis 2018
TABLES = ("caract", "lieux", "vehicules", "usagers")


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def table_de(ressource: dict) -> str | None:
    nom = _norm(ressource.get("title")) + " " + _norm(str(ressource.get("url", "")).rsplit("/", 1)[-1])
    if "immatricul" in nom or "description" in nom:
        return None
    if "usager" in nom:
        return "usagers"
    if "lieux" in nom:
        return "lieux"
    if "vehicule" in nom:
        return "vehicules"
    if "carac" in nom or "carct" in nom or "caract" in nom:
        return "caract"
    return None


def annee_de(ressource: dict) -> int | None:
    for texte in (ressource.get("title"), str(ressource.get("url", "")).rsplit("/", 1)[-1]):
        m = re.search(r"(20\d\d)", str(texte or ""))
        if m:
            return int(m.group(1))
    return None


def inventaire(client) -> dict:
    """{"version": empreinte, "maj": date, "annees": {annee: {table: url}}} (années complètes seulement)."""
    jeu = client.get_json(URL_API)
    choisies: dict[tuple, dict] = {}
    for r in jeu.get("resources") or []:
        if str(r.get("format", "")).lower() not in ("csv", "") or not r.get("url"):
            continue
        t, a = table_de(r), annee_de(r)
        if not t or not a:
            continue
        cle = (a, t)
        if cle not in choisies or (r.get("last_modified") or "") > (choisies[cle].get("last_modified") or ""):
            choisies[cle] = r
    annees: dict[int, dict] = {}
    for (a, t), r in choisies.items():
        annees.setdefault(a, {})[t] = r["url"]
    annees = {a: tables for a, tables in sorted(annees.items()) if all(t in tables for t in TABLES)}
    if not annees:
        raise ValueError("Aucune année complète (4 tables) dans le jeu BAAC")
    empreinte = hashlib.sha1("|".join(f"{a}:{t}:{u}" for a in annees for t, u in sorted(annees[a].items()))
                             .encode()).hexdigest()[:12]
    return {"version": f"{VERSION}-{empreinte}", "maj": (jeu.get("last_modified") or "")[:10] or None,
            "annees": annees}


def lire_csv(chemin: Path):
    """Lignes d'un fichier BAAC, clés en minuscules, valeurs sans espaces superflus."""
    brut = Path(chemin).read_bytes()
    try:
        texte = brut.decode("utf-8-sig")
    except UnicodeDecodeError:
        texte = brut.decode("cp1252", errors="replace")
    entete = texte.split("\n", 1)[0]
    sep = max([";", ",", "\t"], key=entete.count)
    for ligne in csv.DictReader(io.StringIO(texte), delimiter=sep):
        yield {_norm(k): (v or "").strip().replace("\xa0", "") for k, v in ligne.items() if k is not None}


def _num_acc(l: dict) -> str:
    return l.get("num_acc") or l.get("accident_id") or ""


def _entier(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def lieu_ancien_format(dep_brut, com_brut) -> tuple[str | None, str | None]:
    """2005–2018 : « 590 » + « 350 » -> ("59", "59350") ; « 201 » -> Corse-du-Sud (2A)."""
    d = _entier(dep_brut)
    if d is None:
        return None, None
    if d == 201:
        dep = "2A"
    elif d == 202:
        dep = "2B"
    elif d >= 970:
        dep = str(d)
    else:
        dep = f"{d // 10:02d}"
    c = str(com_brut or "").strip()
    if not c.isdigit():
        return dep, None
    return dep, (dep + c.zfill(3)) if len(dep) == 2 else (dep + c.zfill(2))


def lire_annee(annee: int, chemins: dict[str, Path]) -> list[dict]:
    """Une ligne par cycliste pour les accidents de l'année impliquant un vélo ou un VAE."""
    # 1. Véhicules : quels accidents impliquent un vélo, et quels autres véhicules sont en cause
    vehicules: dict[str, list] = {}
    for l in lire_csv(chemins["vehicules"]):
        num, catv = _num_acc(l), _entier(l.get("catv"))
        if num:
            vehicules.setdefault(num, []).append((l.get("num_veh") or "", catv, l.get("obsm") or ""))
    avec_velo = {num: vs for num, vs in vehicules.items() if any(v[1] in CATV_VELO for v in vs)}
    del vehicules

    # 2. Usagers : les cyclistes (conducteurs et passagers d'un vélo) et les piétons heurtés
    cyclistes: dict[str, list] = {}
    pietons: set[str] = set()
    for l in lire_csv(chemins["usagers"]):
        num = _num_acc(l)
        if num not in avec_velo:
            continue
        veh = l.get("num_veh") or ""
        velos = {v[0] for v in avec_velo[num] if v[1] in CATV_VELO}
        catu = l.get("catu")
        if catu == "3" and veh in velos:
            pietons.add(num)
        elif catu in ("1", "2") and veh in velos:
            catv = next((v[1] for v in avec_velo[num] if v[0] == veh), None)
            cyclistes.setdefault(num, []).append((veh, l.get("grav") or "", l.get("trajet") or "", catv))

    # 3. Lieu (département, commune) et 4. situation
    lieux: dict[str, tuple] = {}
    for l in lire_csv(chemins["caract"]):
        num = _num_acc(l)
        if num in cyclistes:
            if annee < 2019:
                lieux[num] = lieu_ancien_format(l.get("dep"), l.get("com"))
            else:
                lieux[num] = (l.get("dep") or None, l.get("com") or None)
    situations: dict[str, str] = {}
    for l in lire_csv(chemins["lieux"]):
        num = _num_acc(l)
        if num in cyclistes and num not in situations:
            situations[num] = l.get("situ") or ""

    lignes = []
    for num, liste in cyclistes.items():
        dep, com = lieux.get(num, (None, None))
        for veh, grav, trajet, catv in liste:
            autres = [str(v[1]) for v in avec_velo[num] if v[0] != veh and v[1] is not None]
            obsm_pieton = any(v[0] == veh and v[2] == "1" for v in avec_velo[num])
            lignes.append({"Num_Acc": num, "an": annee, "dep": dep, "com": com, "grav": grav,
                           "trajet": trajet, "situ": situations.get(num, ""),
                           "typevehicules": " / ".join(autres),
                           "obsm": "1" if (num in pietons or obsm_pieton) else "",
                           "vae": "1" if catv == CATV_VAE else ""})
    return lignes


def lire_tout(client, travail: Path, inv: dict, journal=print) -> list[dict]:
    """Télécharge et lit toutes les années ; une année illisible fait échouer l'ensemble
    (on ne publie pas une série trouée sans le savoir)."""
    toutes = []
    for annee, urls in inv["annees"].items():
        chemins = {t: client.telecharger(u, travail / f"baac-{annee}-{t}.csv") for t, u in urls.items()}
        lignes = lire_annee(annee, chemins)
        if not lignes:
            raise ValueError(f"Aucun cycliste lu pour {annee} : format à vérifier")
        journal(f"    {annee} : {len(lignes)} cyclistes")
        toutes.extend(lignes)
        for c in chemins.values():          # libère le disque au fur et à mesure
            try:
                if str(c).startswith(str(travail)):
                    Path(c).unlink()
            except OSError:
                pass
    return toutes
