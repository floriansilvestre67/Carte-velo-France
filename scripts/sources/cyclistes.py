"""Nombre de cyclistes par commune : actifs qui vont travailler à vélo (Insee, recensement).

Source : Insee, recensement de la population, « Caractéristiques de l'emploi en 2023 », base des
principaux indicateurs (parue le 22/10/2026), jeu « Navettes » (DS_RP_NAVETTES_PRINC), géographie
au 1er janvier 2026. Format « Melodi » : une ligne par (territoire, mode de transport, année) :

  GEO;GEO_OBJECT;TRANS;AGE;EMPSTA_ENQ;WORK_AREA;RP_MEASURE;FREQ;OBS_STATUS;TIME_PERIOD;OBS_VALUE
  69123;COM;3;Y_GE15;1;_T;POP;A;A;2023;31492.43846

  - GEO_OBJECT = COM : communes (on ignore ARM, arrondissements de Paris, Lyon et Marseille,
    puisque la commune entière est aussi présente, et les autres zonages) ;
  - TRANS : mode de transport principal pour aller travailler. Le code du vélo est lu dans le
    fichier de métadonnées (libellé contenant « vélo ») ; « _T » = tous modes = actifs occupés ;
  - TIME_PERIOD : 2012, 2017 et 2023. En 2012, vélo et deux-roues motorisés sont confondus (« 3T4 ») :
    seules les années où le vélo est distingué sont retenues (2017 et 2023) ;
  - OBS_STATUS « K » (valeur comptée dans une autre catégorie) : la valeur n'est pas utilisée.

Limites, rappelées sur le site : seuls les trajets domicile-travail des actifs sont comptés ;
un millésime résume 5 années d'enquêtes ; au-delà de 10 000 habitants, c'est une estimation.
Le fichier est publié sur insee.fr (et non sur data.gouv.fr) : son adresse est fixée ici.
"""

from __future__ import annotations

import csv
import io
import unicodedata
import zipfile
from pathlib import Path

URL_PAGE = "https://www.insee.fr/fr/statistiques/8992172"
URL_FICHIER = "https://www.insee.fr/fr/statistiques/fichier/8992172/DS_RP_NAVETTES_PRINC_2023_CSV_FR.zip"


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return t.lower().strip()


def _nombre(v) -> float | None:
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def _lecteur(flux):
    texte = io.TextIOWrapper(flux, encoding="utf-8-sig", errors="replace", newline="")
    entete = texte.readline()
    sep = max(";,\t", key=entete.count)
    champs = [c.strip() for c in next(csv.reader([entete], delimiter=sep))]
    return csv.DictReader(texte, fieldnames=champs, delimiter=sep)


def code_velo(metadonnees) -> str:
    """Code de la modalité « vélo » de la variable TRANS, lu dans les métadonnées."""
    for l in metadonnees:
        if (l.get("COD_VAR") or "").strip() == "TRANS":
            lib = _norm(l.get("LIB_MOD"))
            if "velo" in lib and "moto" not in lib and "deux" not in lib:
                return (l.get("COD_MOD") or "").strip()
    raise ValueError("modalité « vélo » introuvable dans les métadonnées Insee")


def lire(chemin_zip: Path, correspondance) -> dict:
    """Actifs à vélo et actifs occupés par commune actuelle entière, pour chaque année où le vélo
    est distingué.

    Renvoie {"annees": [2017, 2023], "communes": {code: {"2017": [vélo, actifs], "2023": [...]}},
    "zones": {"D63": {"2017": vélo, "2023": vélo}, "R84": {...}}, "stats": {...}}. Une valeur absente ou non fiable vaut None (jamais 0 par défaut).
    """
    with zipfile.ZipFile(chemin_zip) as z:
        noms = [n for n in z.namelist() if n.lower().endswith(".csv")]
        meta = next((n for n in noms if "metadata" in n.lower()), None)
        data = next((n for n in noms if "metadata" not in n.lower()), None)
        if not meta or not data:
            raise ValueError(f"fichiers inattendus dans le zip Insee : {noms}")
        with z.open(meta) as f:
            velo = code_velo(_lecteur(f))
        brut: dict[str, dict[str, dict]] = {}     # code -> année -> {"v": .., "a": ..}
        zones: dict[str, dict] = {}               # "D63" / "R84" -> année -> actifs à vélo
        stats = {"lignes": 0, "inconnues": 0, "non_fiables": 0}
        annees_velo: set[str] = set()
        with z.open(data) as f:
            for l in _lecteur(f):
                stats["lignes"] += 1
                niveau = l.get("GEO_OBJECT")
                if niveau not in ("COM", "DEP", "REG") or l.get("WORK_AREA") != "_T":
                    continue
                trans = l.get("TRANS")
                if trans not in (velo, "_T"):
                    continue
                an = (l.get("TIME_PERIOD") or "").strip()
                if trans == velo:
                    annees_velo.add(an)
                cle = "v" if trans == velo else "a"
                valeur = _nombre(l.get("OBS_VALUE"))
                if (l.get("OBS_STATUS") or "A") == "K":
                    stats["non_fiables"] += 1
                    valeur = None
                code = l["GEO"].strip()
                if niveau == "COM":
                    brut.setdefault(code, {}).setdefault(an, {})[cle] = valeur
                elif trans == velo:                # départements et régions : directement l'Insee
                    zones.setdefault(niveau[0] + code, {})[an] = None if valeur is None else round(valeur)

    annees = sorted(int(a) for a in annees_velo)
    if not annees:
        raise ValueError("aucune année avec le vélo distingué dans le fichier Insee")

    communes: dict[str, dict] = {}
    for code, par_an in brut.items():
        entiere = correspondance.resoudre(code) if correspondance else code
        if not entiere:
            stats["inconnues"] += 1
            continue
        fiche = communes.setdefault(entiere, {})
        for an in annees:
            d = par_an.get(str(an)) or {}
            v, a = d.get("v"), d.get("a")
            ancien = fiche.get(str(an))
            if ancien is None:
                fiche[str(an)] = [v, a]
            else:                                 # deux anciennes communes regroupées depuis
                fiche[str(an)] = [None if ancien[0] is None or v is None else ancien[0] + v,
                                  None if ancien[1] is None or a is None else ancien[1] + a]
    for fiche in communes.values():
        for an, (v, a) in fiche.items():
            fiche[an] = [None if v is None else round(v), None if a is None else round(a)]
    stats["communes"] = len(communes)
    zones = {z: {an: v for an, v in par_an.items() if int(an) in annees} for z, par_an in zones.items()}
    return {"annees": annees, "communes": communes, "zones": zones, "stats": stats}


def format_valide(cyc) -> bool:
    """Vrai pour le format publié actuel {"2017": [v, a], ...} (et non l'ancien {"v", "a"})."""
    return isinstance(cyc, dict) and bool(cyc) and all(str(k).isdigit() for k in cyc)
