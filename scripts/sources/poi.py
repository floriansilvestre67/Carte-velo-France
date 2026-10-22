"""Points d'intérêt à voir à vélo.

Sources (toutes en Licence Ouverte) :
  - DATAtourisme (ADN Tourisme) : exports CSV « place », « tour » et « product » de data.gouv.fr.
    L'API DATAtourisme demande une clé et pagine des centaines de milliers de lieux ; les exports
    CSV quotidiens contiennent les mêmes lieux en trois fichiers.
  - Monuments historiques (Ministère de la Culture, base Mérimée) : CSV complet, coordonnées WGS84.
  - Musées de France (Ministère de la Culture, base Muséofile), qui remplace l'ancienne liste archivée.

Sélection DATAtourisme (classes de l'ontologie, dernier segment de l'URI) :
  gardés  : sites culturels et patrimoine, musées, parcs et jardins, patrimoine naturel,
            itinéraires vélo (CyclingTour), location et réparation de vélos ;
  écartés : hébergement, restauration, événements, commerces, fermes, bibliothèques, salles.

Dédoublonnage : un monument ou un musée officiel qui correspond à un lieu DATAtourisme de la
même famille (moins de 150 m et noms proches, ou moins de 30 m) n'est gardé qu'une fois ;
la fiche garde le nom DATAtourisme et prend le statut officiel (classé MH, musée de France).
"""

from __future__ import annotations

import csv
import io
import math
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from sources.communes import departement_du_code

ID_DATATOURISME = "5b598be088ee387c0c353714"
ID_MERIMEE = "5af120e5b595087cfabcde81"
ID_MUSEOFILE = "5d12ee8206e3e762c0c89a4c"
URL_API = "https://www.data.gouv.fr/api/1/datasets/{}/"

csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))

# Catégories publiées (l'ordre sert aussi de priorité pour « les incontournables »)
CATEGORIES = ["Musée", "Monument historique", "Patrimoine", "Parc ou jardin", "Nature et point de vue",
              "Itinéraire vélo", "Location ou réparation de vélos"]
C_MUSEE, C_MH, C_PATRIMOINE, C_PARC, C_NATURE, C_ITINERAIRE, C_SERVICE = range(7)
FAMILLE = {C_MUSEE: "musee", C_MH: "patrimoine", C_PATRIMOINE: "patrimoine"}

CLASSES_MUSEE = {"museum"}
CLASSES_PATRIMOINE = {"culturalsite", "cityheritage", "religioussite", "church", "cathedral", "chapel", "abbey",
                      "convent", "collegiate", "basilica", "castle", "chateau", "defencesite", "fortifiedsite",
                      "archeologicalsite", "ruins", "remarkablebuilding", "monument", "technicalheritage",
                      "industrialsite", "mill", "bridge", "lighthouse", "remarkablehouse", "manor", "palace",
                      "interpretationcentre", "memorial", "tower"}
CLASSES_PARC = {"parkandgarden", "park", "garden", "botanicalgarden"}
CLASSES_NATURE = {"naturalheritage", "pointofview", "viewpoint", "landform", "beach", "lake", "waterfall", "cave",
                  "forest", "naturalreserve", "naturalpark", "geologicalsite", "gorge", "river"}
CLASSES_ITINERAIRE = {"cyclingtour"}
CLASSES_SERVICE = {"bikestationordepot", "bikerental"}
CLASSES_SERVICE_SI_VELO = {"equipmentrental", "equipmentrentalshop", "rental", "equipmentrepairshop", "repairshop"}
CLASSES_EXCLUES = {"accommodation", "foodestablishment", "restaurant", "hotel", "camping", "campsite", "gite",
                   "bedandbreakfast", "holidayresort", "rentalaccommodation", "library", "movietheater", "theater",
                   "conventioncentre", "farm", "teachingfarm", "store", "shop", "event", "entertainmentandevent",
                   "winecellar", "bar", "casino"}
MOTS_VELO = re.compile(r"v[ée]lo|bike|cycl|vtt|vtc", re.I)


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def classes(categories: str) -> set[str]:
    """« https://…/core#Museum|http://schema.org/Museum » -> {"museum"}"""
    res = set()
    for uri in str(categories or "").split("|"):
        uri = uri.strip()
        if uri:
            res.add(re.split(r"[#/]", uri)[-1].lower())
    return res


def categorie_datatourisme(cl: set[str], nom: str) -> int | None:
    if cl & CLASSES_EXCLUES:
        return None
    if cl & CLASSES_MUSEE:
        return C_MUSEE
    if cl & CLASSES_ITINERAIRE:
        return C_ITINERAIRE
    if cl & CLASSES_SERVICE or (cl & CLASSES_SERVICE_SI_VELO and MOTS_VELO.search(nom or "")):
        return C_SERVICE
    if cl & CLASSES_PATRIMOINE:
        return C_PATRIMOINE
    if cl & CLASSES_PARC:
        return C_PARC
    if cl & CLASSES_NATURE:
        return C_NATURE
    return None


def _nombre(v):
    try:
        return float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def coordonnees(texte):
    """« 48.39, 4.52 » -> (lat, lon)"""
    morceaux = [m for m in re.split(r"[,;\s]+", str(texte or "").strip()) if m]
    if len(morceaux) != 2:
        return None
    lat, lon = _nombre(morceaux[0]), _nombre(morceaux[1])
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def lignes_csv(chemin: Path):
    """Itère sur un gros CSV (séparateur deviné sur les premières lignes)."""
    with open(chemin, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        debut = f.read(20000)
        f.seek(0)
        try:
            dialecte = csv.Sniffer().sniff(debut, delimiters=",;\t")
        except csv.Error:
            dialecte = csv.excel
        yield from csv.DictReader(f, dialect=dialecte)


def _court(t, n=180) -> str:
    t = " ".join(str(t or "").split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def ressources_datatourisme(client) -> list[dict]:
    jeu = client.get_json(URL_API.format(ID_DATATOURISME))
    voulus = {"datatourisme-place.csv", "datatourisme-tour.csv", "datatourisme-product.csv"}
    res = [r for r in jeu.get("resources") or [] if str(r.get("title", "")).lower() in voulus and r.get("url")]
    if not res:
        raise ValueError("Exports CSV DATAtourisme introuvables")
    return res


def ressource_csv(client, id_jeu: str) -> dict:
    jeu = client.get_json(URL_API.format(id_jeu))
    for r in jeu.get("resources") or []:
        if str(r.get("format", "")).lower() == "csv" and r.get("url"):
            return r
    raise ValueError(f"Aucun CSV dans le jeu {id_jeu}")


class Placeur:
    """Rattache un point à sa commune et à son département (métropole uniquement)."""

    def __init__(self, codes_valides, localisateur_dep, localisateur_communes=None):
        self.codes = codes_valides
        self.dep = localisateur_dep
        self.com = localisateur_communes

    def placer(self, lat, lon):
        com = self.com.trouver(lon, lat) if self.com is not None else None
        dep = departement_du_code(com) if com else self.dep.trouver(lon, lat)
        return (dep, com) if dep in self.codes else (None, None)


def lire_datatourisme(chemins: list[Path], placeur: Placeur, stats: dict) -> list[dict]:
    lieux, vus = [], set()
    gardees, ecartees = Counter(), Counter()
    for chemin in chemins:
        for l in lignes_csv(chemin):
            stats["datatourisme_lignes"] += 1
            uri = l.get("URI_ID_du_POI") or ""
            if uri and uri in vus:
                continue
            nom = (l.get("Nom_du_POI") or "").strip()
            cl = classes(l.get("Categories_de_POI"))
            cat = categorie_datatourisme(cl, nom)
            specifiques = cl - {"pointofinterest", "placeofinterest", "thing", "product", "tour", "orderedlist"}
            (gardees if cat is not None else ecartees).update(specifiques)
            if cat is None or not nom:
                continue
            lat, lon = _nombre(l.get("Latitude")), _nombre(l.get("Longitude"))
            if lat is None or lon is None:
                continue
            dep, com = placeur.placer(lat, lon)
            if not dep:
                continue
            vus.add(uri)
            lieux.append({"lat": lat, "lon": lon, "nom": nom, "cat": cat, "dep": dep, "com": com,
                          "src": "DATAtourisme", "lien": uri, "desc": _court(l.get("Description")), "statut": ""})
    stats["classes_gardees"] = dict(gardees.most_common(40))
    stats["classes_ecartees"] = dict(ecartees.most_common(40))
    return lieux


def lire_merimee(chemin: Path, placeur: Placeur, stats: dict) -> list[dict]:
    lieux = []
    for l in lignes_csv(chemin):
        stats["merimee_lignes"] += 1
        pos = coordonnees(l.get("coordonnees_au_format_WGS84"))
        if not pos:
            continue
        dep, com = placeur.placer(*pos)
        if not dep:
            continue
        nom = (l.get("Titre_editorial_de_la_notice") or l.get("Denomination_de_l_edifice") or "").strip()
        if not nom:
            continue
        protection = _norm(l.get("Typologie_de_la_protection") or l.get("Nature_de_la_protection"))
        statut = "classé MH" if "class" in protection else "inscrit MH" if "inscri" in protection else "protégé MH"
        ref = (l.get("Reference") or "").strip()
        siecle = _court(l.get("Format_abrege_du_siecle_de_construction") or l.get("Siecle_de_la_campagne_principale_de_construction"), 60)
        lieux.append({"lat": pos[0], "lon": pos[1], "nom": nom, "cat": C_MH, "dep": dep, "com": com,
                      "src": "Mérimée", "lien": f"https://pop.culture.gouv.fr/notice/merimee/{ref}" if ref else "",
                      "desc": siecle, "statut": statut})
    return lieux


def lire_museofile(chemin: Path, placeur: Placeur, stats: dict) -> list[dict]:
    lieux = []
    for l in lignes_csv(chemin):
        stats["museofile_lignes"] += 1
        pos = coordonnees(l.get("Coordonnees"))
        if not pos:
            continue
        dep, com = placeur.placer(*pos)
        nom = (l.get("Nom_officiel") or "").strip()
        if not dep or not nom:
            continue
        url = (l.get("URL") or "").strip()
        if url and not url.startswith("http"):
            url = "https://" + url
        lieux.append({"lat": pos[0], "lon": pos[1], "nom": nom, "cat": C_MUSEE, "dep": dep, "com": com,
                      "src": "Muséofile", "lien": url, "desc": _court(l.get("Atout") or l.get("Themes")),
                      "statut": "musée de France"})
    return lieux


def _distance_m(a, b) -> float:
    dlat = (a["lat"] - b["lat"]) * 111_320
    dlon = (a["lon"] - b["lon"]) * 111_320 * math.cos(math.radians(a["lat"]))
    return math.hypot(dlat, dlon)


def _proches(a: str, b: str) -> bool:
    ma = {m for m in _norm(a).split() if len(m) > 2}
    mb = {m for m in _norm(b).split() if len(m) > 2}
    if not ma or not mb:
        return False
    return len(ma & mb) / min(len(ma), len(mb)) >= 0.5


def dedoublonner(datatourisme: list[dict], officiels: list[dict], stats: dict) -> list[dict]:
    """Fusionne un lieu officiel avec le lieu DATAtourisme de même famille qui lui correspond."""
    grille: dict[tuple, list] = {}
    for d in datatourisme:
        if d["cat"] in FAMILLE:
            grille.setdefault((round(d["lat"], 2), round(d["lon"], 2)), []).append(d)
    gardes = []
    for o in officiels:
        cx, cy = round(o["lat"], 2), round(o["lon"], 2)
        voisins = [d for dx in (-0.01, 0, 0.01) for dy in (-0.01, 0, 0.01)
                   for d in grille.get((round(cx + dx, 2), round(cy + dy, 2)), [])
                   if FAMILLE.get(d["cat"]) == FAMILLE[o["cat"]]]
        double = None
        for d in voisins:
            dist = _distance_m(o, d)
            if dist < 30 or (dist < 150 and _proches(o["nom"], d["nom"])):
                double = d
                break
        if double is not None:
            stats["doublons"] += 1
            double["statut"] = double["statut"] or o["statut"]
            if o["cat"] == C_MH and double["cat"] == C_PATRIMOINE:
                double["cat"] = C_MH
            double.setdefault("autre_lien", o["lien"])
        else:
            gardes.append(o)
    return datatourisme + gardes


CHAMPS = ["lat", "lon", "nom", "categorie", "commune", "source", "lien", "description", "statut"]
SOURCES = ["DATAtourisme", "Mérimée", "Muséofile"]


def calculer(client, travail: Path, codes_valides: set[str], localisateur_dep, localisateur_communes=None) -> dict:
    stats = Counter()
    placeur = Placeur(codes_valides, localisateur_dep, localisateur_communes)
    chemins = []
    for r in ressources_datatourisme(client):
        chemins.append(client.telecharger(r["url"], travail / r["title"]))
    dt = lire_datatourisme(chemins, placeur, stats)
    officiels, erreurs = [], []
    for id_jeu, lire, nom in ((ID_MUSEOFILE, lire_museofile, "museofile"), (ID_MERIMEE, lire_merimee, "merimee")):
        try:
            r = ressource_csv(client, id_jeu)
            officiels += lire(client.telecharger(r["url"], travail / f"{nom}.csv"), placeur, stats)
        except Exception as e:  # une source complémentaire en panne n'empêche pas les autres
            erreurs.append(f"{nom} : {e}")
    tous = dedoublonner(dt, officiels, stats)
    par_dep: dict[str, list] = {}
    for p in tous:
        par_dep.setdefault(p["dep"], []).append([
            round(p["lat"], 5), round(p["lon"], 5), p["nom"], p["cat"], p["com"] or "",
            SOURCES.index(p["src"]), p["lien"], p["desc"], p["statut"]])
    comptes = Counter(CATEGORIES[p["cat"]] for p in tous)
    if not tous:
        raise ValueError("Aucun point d'intérêt retenu")
    return {"par_dep": par_dep, "stats": dict(stats), "comptes": dict(comptes), "erreurs": erreurs}
