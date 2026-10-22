"""Stationnement vélo.

A) Indicateurs officiels (Tableau de bord des mobilités durables, Ecolab, ODbL), calculés
   à partir de la base nationale du stationnement cyclable (OpenStreetMap) :
     - « Nombre de places de stationnement vélo », par type d'accroche ;
     - « Nombre de places sécurisées (accroche cadre et roue, ou cadre) pour 1 000 hab. ».
   Fichiers CSV par niveau (commune, département…) ; on garde le relevé le plus récent.
   URL retrouvées via l'API data.gouv.fr. Choix du fichier plutôt que de l'API tabulaire :
   quelques dizaines de Mo, téléchargés en une fois, sans limite de requêtes.

B) Emplacements (« Stationnements cyclables issus d'OpenStreetMap », schéma
   etalab/schema-stationnement-cyclable, ODbL) : GeoJSON zippé publié par geodatamine.fr.
   Le gros CSV non zippé est obsolète et signalé invalide : on ne l'utilise pas.

Définition retenue de « sécurisé » (identique à l'indicateur officiel) : type d'accroche
« cadre » ou « cadre et roue ». Les box et consignes fermées sont signalées à part.
"""

from __future__ import annotations

import csv
import io
import unicodedata
import zipfile
from pathlib import Path

import ijson

from sources.communes import commune_entiere, departement_du_code

ID_PLACES = "67cad6cecc9d655511810ad9"
ID_SECURISEES = "6895bfae168e9214a9c28369"
URL_API = "https://www.data.gouv.fr/api/1/datasets/{}/"
ID_OSM = "614d7cd3474124ea1fa212f1"
URL_OSM_DEFAUT = "https://geodatamine.fr/dump/bicycle_parking_geojson.zip"

ACCROCHES_SECURISEES = {"cadre", "cadre et roue"}


def _norm(v) -> str:
    t = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(t.replace("_", " ").split())


# --------------------------------------------------------------------------
# A) Indicateurs Ecolab
# --------------------------------------------------------------------------

def ressource(client, id_jeu: str, niveau: str) -> dict:
    """Ressource CSV « … - commune » ou « … - departement » du jeu."""
    jeu = client.get_json(URL_API.format(id_jeu))
    for r in jeu.get("resources") or []:
        titre = _norm(r.get("title"))
        if titre.endswith("- " + niveau) and r.get("url"):
            return r
    raise ValueError(f"Ressource « {niveau} » introuvable dans le jeu {id_jeu}")


def lire_csv(chemin: Path):
    with open(chemin, "rb") as f:
        brut = f.read()
    texte = brut.decode("utf-8-sig", errors="replace")
    echantillon = texte[:5000]
    try:
        dialecte = csv.Sniffer().sniff(echantillon, delimiters=",;\t")
    except csv.Error:
        dialecte = csv.excel
    return list(csv.DictReader(io.StringIO(texte), dialect=dialecte))


def _date(ligne) -> str:
    return str(ligne.get("date_mesure") or "")[:10]


def _nombre(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def agreger_places(lignes, cle_code: str) -> tuple[dict, str | None]:
    """{code: {"places": total, "places_secu": cadre + cadre et roue}} au relevé le plus récent."""
    dates = sorted({_date(l) for l in lignes if _date(l)})
    if not dates:
        raise ValueError("Aucune date de mesure dans le fichier des places")
    derniere = dates[-1]
    res: dict[str, dict] = {}
    for l in lignes:
        if _date(l) != derniere:
            continue
        code = str(l.get(cle_code) or "").strip().upper()
        v = _nombre(l.get("valeur"))
        if not code or v is None:
            continue
        if cle_code == "geocode_commune":
            code = commune_entiere(code.zfill(5))
        r = res.setdefault(code, {"places": 0, "places_secu": 0})
        r["places"] += v
        if _norm(l.get("type_accroche")) in ACCROCHES_SECURISEES:
            r["places_secu"] += v
    return res, derniere


def agreger_securisees(lignes, cle_code: str) -> tuple[dict, str | None]:
    """{code: places sécurisées pour 1 000 hab.} au relevé le plus récent (valeur officielle)."""
    dates = sorted({_date(l) for l in lignes if _date(l)})
    if not dates:
        raise ValueError("Aucune date de mesure dans le fichier des places sécurisées")
    derniere = dates[-1]
    num, den, val = {}, {}, {}
    for l in lignes:
        if _date(l) != derniere:
            continue
        code = str(l.get(cle_code) or "").strip().upper()
        if not code:
            continue
        if cle_code == "geocode_commune":
            code = commune_entiere(code.zfill(5))
        n, d = _nombre(l.get("numerateur")), _nombre(l.get("denominateur"))
        if n is not None and d:
            num[code] = num.get(code, 0) + n
            den[code] = den.get(code, 0) + d
        elif _nombre(l.get("valeur")) is not None:
            val[code] = _nombre(l.get("valeur"))
    res = {c: num[c] / den[c] * 1000 for c in num if den.get(c)}
    for c, v in val.items():
        res.setdefault(c, v)
    return res, derniere


def indicateurs(client, travail: Path) -> dict:
    sortie = {}
    for niveau, cle in (("departement", "geocode_departement"), ("commune", "geocode_commune")):
        r1 = ressource(client, ID_PLACES, niveau)
        r2 = ressource(client, ID_SECURISEES, niveau)
        f1 = client.telecharger(r1["url"], travail / f"places-{niveau}.csv")
        f2 = client.telecharger(r2["url"], travail / f"securisees-{niveau}.csv")
        places, date1 = agreger_places(lire_csv(f1), cle)
        secu, date2 = agreger_securisees(lire_csv(f2), cle)
        sortie[niveau] = {"places": places, "secu_1000": secu, "date_places": date1, "date_secu": date2,
                          "url_places": r1["url"], "url_secu": r2["url"]}
    return sortie


# --------------------------------------------------------------------------
# B) Emplacements OpenStreetMap
# --------------------------------------------------------------------------

CHAMPS_POINT = ["lat", "lon", "capacite", "capacite_cargo", "accroche", "mobilier", "protection", "acces",
                "gratuit", "couverture", "surveillance"]


def url_osm(client) -> str:
    """URL du GeoJSON zippé, retrouvée via l'API data.gouv.fr (repli : adresse connue)."""
    try:
        jeu = client.get_json(URL_API.format(ID_OSM))
        for r in jeu.get("resources") or []:
            if "geojson" in _norm(r.get("format")) + _norm(r.get("title")) and r.get("url"):
                return r["url"]
    except Exception:
        pass
    return URL_OSM_DEFAUT


def _bool(v):
    t = _norm(v)
    if t in ("true", "oui", "yes", "1"):
        return 1
    if t in ("false", "non", "no", "0"):
        return 0
    return None


def _entier(v):
    n = _nombre(v)
    return int(n) if n is not None and n >= 0 else None


def lire_emplacements(chemin: Path, codes_valides: set[str], localisateur=None) -> dict:
    valeurs = {"accroche": [], "mobilier": [], "protection": [], "acces": []}
    positions: dict[str, dict[str, int]] = {k: {} for k in valeurs}

    def indice(champ, v):
        """Indice du libellé dans la liste du champ ; le libellé publié garde ses accents."""
        cle = _norm(v)
        if not cle:
            return -1
        if cle not in positions[champ]:
            positions[champ][cle] = len(valeurs[champ])
            valeurs[champ].append(" ".join(str(v).replace("_", " ").split()).lower())
        return positions[champ][cle]

    par_dep: dict[str, list] = {}
    stats = {"points": 0, "hors_metropole": 0, "sans_capacite": 0, "places": {}}
    with zipfile.ZipFile(chemin) as z:
        noms = [n for n in z.namelist() if n.lower().endswith((".geojson", ".json"))]
        if not noms:
            raise ValueError("Archive sans fichier GeoJSON")
        with z.open(noms[0]) as f:
            for feat in ijson.items(f, "features.item", use_float=True):
                p = feat.get("properties") or {}
                g = feat.get("geometry") or {}
                coords = g.get("coordinates") if g.get("type") == "Point" else None
                lon = coords[0] if coords else _nombre(p.get("xlong"))
                lat = coords[1] if coords else _nombre(p.get("ylat"))
                if lon is None or lat is None:
                    continue
                code = str(p.get("code_com") or "").strip().upper()
                dep = departement_du_code(code.zfill(5)) if code else None
                if dep not in codes_valides and localisateur is not None:
                    dep = localisateur.trouver(lon, lat)
                if dep not in codes_valides:
                    stats["hors_metropole"] += 1
                    continue
                stats["points"] += 1
                cap = _entier(p.get("capacite"))
                if cap is None:
                    stats["sans_capacite"] += 1
                stats["places"][dep] = stats["places"].get(dep, 0) + (cap or 0)
                par_dep.setdefault(dep, []).append([
                    round(lat, 5), round(lon, 5), cap, _entier(p.get("capacite_cargo")),
                    indice("accroche", p.get("type_accroche")), indice("mobilier", p.get("mobilier")),
                    indice("protection", p.get("protection")), indice("acces", p.get("acces")),
                    _bool(p.get("gratuit")), _bool(p.get("couverture")), _bool(p.get("surveillance"))])
    if stats["points"] == 0:
        raise ValueError("Aucun emplacement de stationnement lu")
    return {"par_dep": par_dep, "valeurs": valeurs, "stats": stats}


def emplacements(client, travail: Path, codes_valides: set[str], localisateur=None) -> dict:
    url = url_osm(client)
    chemin = client.telecharger(url, travail / "stationnement-osm.zip")
    res = lire_emplacements(chemin, codes_valides, localisateur)
    res["url"] = url
    return res


def coherence(places_osm: dict[str, int], places_officielles: dict[str, float]) -> dict:
    """Compare le total des capacités OSM au total officiel, globalement et par département."""
    total_osm = sum(places_osm.values())
    total_off = sum(v["places"] for v in places_officielles.values())
    ecarts = []
    for dep, off in places_officielles.items():
        if off["places"]:
            ecarts.append({"dep": dep, "osm": places_osm.get(dep, 0), "officiel": round(off["places"]),
                           "ecart_pct": round((places_osm.get(dep, 0) - off["places"]) / off["places"] * 100, 1)})
    ecarts.sort(key=lambda e: -abs(e["ecart_pct"]))
    return {"total_osm": total_osm, "total_officiel": round(total_off),
            "ecart_pct": round((total_osm - total_off) / total_off * 100, 1) if total_off else None,
            "plus_grands_ecarts": ecarts[:10]}
