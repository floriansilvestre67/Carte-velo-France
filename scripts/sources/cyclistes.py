"""Nombre de cyclistes par commune : actifs qui vont travailler à vélo (Insee, recensement).

Source : Insee, recensement de la population, « Caractéristiques de l'emploi », base des
principaux indicateurs par commune (exploitation principale). Variable retenue :
  P21_ACTOCC15P_VELO = actifs occupés de 15 ans ou plus dont le vélo (y compris à assistance
  électrique) est le principal mode de transport pour aller travailler ;
  P21_ACTOCC15P      = ensemble des actifs occupés de 15 ans ou plus (pour la part).

Limites, rappelées sur le site :
  - seuls les trajets domicile-travail des actifs sont comptés (ni étudiants, ni retraités, ni loisirs) ;
  - le vélo n'est distingué des deux-roues motorisés que depuis l'enquête 2015 : il n'y a
    donc pas de série longue ; un millésime « 2021 » résume les enquêtes de 2019 à 2023 ;
  - au-delà de 10 000 habitants, le chiffre est une estimation sur échantillon.

Le fichier est publié sur insee.fr (et non sur data.gouv.fr) : son adresse est donc fixée ici.
Le nom des colonnes est retrouvé par motif (P + deux chiffres), pour suivre un futur millésime.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

from sources.communes import commune_entiere

URL_PAGE = "https://www.insee.fr/fr/statistiques/8200707"
URL_FICHIER = "https://www.insee.fr/fr/statistiques/fichier/8200707/base-cc-caract_emp-2021_csv.zip"

# Version 2023 (parue le 22/10/2026) au nouveau format « Melodi » : pas encore lue, seulement
# décrite dans le journal de l'Action pour préparer le passage à ce millésime.
URL_DIAG_2023 = "https://www.insee.fr/fr/statistiques/fichier/8992172/DS_RP_NAVETTES_PRINC_2023_CSV_FR.zip"

MOTIF_VELO = re.compile(r"^P(\d\d)_ACTOCC15P_VELO$")


def _nombre(v) -> float | None:
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def _lignes(flux: bytes):
    """Lignes d'un CSV Insee (séparateur lu sur l'en-tête ; UTF-8, sinon Latin-1)."""
    try:
        texte = flux.decode("utf-8-sig")
    except UnicodeDecodeError:
        texte = flux.decode("latin-1")
    entete = texte.split("\n", 1)[0]
    sep = max(";,\t", key=entete.count)
    return csv.DictReader(io.StringIO(texte), delimiter=sep)


def lire(chemin_zip: Path, correspondance) -> dict:
    """Actifs à vélo et actifs occupés par commune actuelle entière.

    Renvoie {"annee": 2021, "communes": {code: {"v": vélo, "a": actifs}}, "stats": {...}}.
    Les arrondissements de Paris, Lyon et Marseille ne servent que si la commune entière manque ;
    les anciennes communes (fusions plus récentes que le fichier) sont ramenées à la commune actuelle.
    """
    annee = None
    communes: dict[str, dict] = {}
    arrondissements: dict[str, dict] = {}
    stats = {"lignes": 0, "inconnues": 0}
    with zipfile.ZipFile(chemin_zip) as z:
        for nom in z.namelist():
            if not nom.lower().endswith(".csv"):
                continue
            lecteur = _lignes(z.read(nom))
            champs = lecteur.fieldnames or []
            col_velo = next((c for c in champs if MOTIF_VELO.match(c.strip())), None)
            col_geo = next((c for c in champs if c.strip().upper() == "CODGEO"), None)
            if not col_velo or not col_geo:
                continue                              # fichier de métadonnées, ou autre table
            yy = MOTIF_VELO.match(col_velo.strip()).group(1)
            annee = 2000 + int(yy)
            col_act = next((c for c in champs if c.strip() == f"P{yy}_ACTOCC15P"), None)
            for l in lecteur:
                stats["lignes"] += 1
                code = (l.get(col_geo) or "").strip()
                v = _nombre(l.get(col_velo))
                if not code or v is None:
                    continue
                a = _nombre(l.get(col_act)) if col_act else None
                entiere = correspondance.resoudre(code) if correspondance else code
                if not entiere:
                    stats["inconnues"] += 1
                    continue
                cible = arrondissements if commune_entiere(code) != code else communes
                fiche = cible.setdefault(entiere, {"v": 0.0, "a": 0.0 if a is not None else None})
                fiche["v"] += v
                if a is not None and fiche["a"] is not None:
                    fiche["a"] += a
                elif a is None:
                    fiche["a"] = None
    if annee is None:
        raise ValueError("colonne Pxx_ACTOCC15P_VELO introuvable dans le fichier Insee")
    for code, fiche in arrondissements.items():
        communes.setdefault(code, fiche)            # seulement si la commune entière manque
    for fiche in communes.values():
        fiche["v"] = round(fiche["v"])
        if fiche["a"] is not None:
            fiche["a"] = round(fiche["a"])
    stats["communes"] = len(communes)
    return {"annee": annee, "communes": communes, "stats": stats}


def par_departement(communes: dict, correspondance) -> dict[str, int]:
    """Total des actifs à vélo par département."""
    total: dict[str, int] = {}
    for code, fiche in communes.items():
        dep = correspondance.departement(code) if correspondance else None
        if dep:
            total[dep] = total.get(dep, 0) + fiche["v"]
    return total


def decrire_zip(chemin_zip: Path) -> list[str]:
    """Décrit la structure d'un fichier Insee au format Melodi (en-têtes, valeurs des colonnes
    de dimension, lignes d'exemple pour Lyon), pour préparer sa lecture. Diagnostic provisoire."""
    sortie = []
    with zipfile.ZipFile(chemin_zip) as z:
        for info in z.infolist():
            sortie.append(f"{info.filename} ({info.file_size / 1e6:.1f} Mo)")
            if not info.filename.lower().endswith(".csv"):
                continue
            with z.open(info) as f:
                texte = io.TextIOWrapper(f, encoding="utf-8-sig", errors="replace")
                entete = texte.readline()
                sep = max(";,\t", key=entete.count)
                champs = next(csv.reader([entete], delimiter=sep))
                sortie.append(f"  séparateur {sep!r}, colonnes : {champs}")
                petit = info.file_size < 2_000_000            # fichier de métadonnées : on le recopie
                valeurs = {c: {} for c in champs}
                exemples = 0
                for i, ligne in enumerate(csv.reader(texte, delimiter=sep)):
                    if i < 5 or (petit and i < 400):
                        sortie.append(f"  ligne : {ligne}")
                    elif exemples < 80 and any("69123" in v for v in ligne):
                        sortie.append(f"  Lyon : {ligne}")
                        exemples += 1
                    for c, v in zip(champs, ligne):
                        d = valeurs[c]
                        if len(d) <= 80 or v in d:
                            d[v] = d.get(v, 0) + 1
                for c, d in valeurs.items():
                    if len(d) <= 80:
                        sortie.append(f"  {c} : {sorted(d.items())}")
                    else:
                        sortie.append(f"  {c} : plus de 80 valeurs, par ex. {list(d)[:10]}")
    return sortie
