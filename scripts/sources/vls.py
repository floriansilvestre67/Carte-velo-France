"""Vélos en libre-service : flux GBFS référencés sur transport.data.gouv.fr.

Principe :
  1. on liste les jeux de données de partage de véhicules et leurs ressources « gbfs » ;
  2. pour chaque flux, on lit le fichier de découverte (gbfs.json), puis les flux utiles :
       - vehicle_types        : types de véhicules (pour écarter trottinettes, voitures…)
       - station_information  : position des stations
       - station_status       : vélos disponibles en station
       - free_bike_status (1.x/2.x) ou vehicle_status (3.x) : vélos en free-floating
  3. chaque station et chaque vélo libre est rattaché à son département par sa position.

Le « nombre de vélos » est un instantané : vélos disponibles au moment de la mise à jour.
Un flux en panne est ignoré (et signalé dans le journal), il ne bloque pas les autres.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

URL_API_JEUX = "https://transport.data.gouv.fr/api/datasets"

# L'ancien type « bike-scooter-sharing » semble remplacé par « vehicles-sharing » : on accepte les deux.
TYPES_JEUX = {"bike-scooter-sharing", "vehicles-sharing"}

FORMES_VELO = {"bicycle", "cargo_bicycle"}
MOTS_VELO = ("bike", "bicycle", "velo", "vélo", "cycle", "vls")
MOTS_NON_VELO = ("car", "scooter", "trottinette", "moped", "autopartage", "covoiturage")


def _texte(valeur) -> str:
    """Les noms GBFS 3.x sont des listes [{text, language}] ; les 1.x/2.x de simples chaînes."""
    if isinstance(valeur, list):
        for v in valeur:
            if isinstance(v, dict) and v.get("text"):
                return str(v["text"])
        return ""
    return str(valeur) if valeur else ""


def _contient(texte: str, mots) -> bool:
    t = texte.lower()
    return any(m in t for m in mots)


# --------------------------------------------------------------------------
# 1. Liste des flux
# --------------------------------------------------------------------------

def lister_flux(client) -> list[dict]:
    jeux = client.get_json(URL_API_JEUX)
    if not isinstance(jeux, list):
        raise ValueError("Réponse inattendue de l'API transport.data.gouv.fr")
    flux, vus = [], set()
    for jeu in jeux:
        if jeu.get("type") not in TYPES_JEUX:
            continue
        sous_types = [str(s.get("name") if isinstance(s, dict) else s) for s in jeu.get("sub_types") or []]
        # Un jeu explicitement typé « autopartage » ou « trottinettes » sans mention de vélo est écarté.
        if sous_types and not any(_contient(s, MOTS_VELO) for s in sous_types) \
                and any(_contient(s, MOTS_NON_VELO) for s in sous_types):
            continue
        for r in jeu.get("resources") or []:
            if str(r.get("format", "")).lower() != "gbfs":
                continue
            url = r.get("url") or r.get("original_url")
            if url and url not in vus:
                vus.add(url)
                flux.append({"jeu": jeu.get("title") or "", "url": url})
    return flux


# --------------------------------------------------------------------------
# 2. Lecture d'un système GBFS
# --------------------------------------------------------------------------

def lire_decouverte(doc: dict) -> dict[str, str]:
    """gbfs.json -> {nom_du_flux: url}, pour GBFS 1.x, 2.x et 3.x."""
    data = doc.get("data") or {}
    if isinstance(data.get("feeds"), list):          # 3.x : pas de niveau langue
        feeds = data["feeds"]
    else:                                            # 1.x / 2.x : data.{langue}.feeds
        langues = [v for v in data.values() if isinstance(v, dict) and isinstance(v.get("feeds"), list)]
        langue = data.get("fr") if isinstance(data.get("fr"), dict) else (langues[0] if langues else {})
        feeds = langue.get("feeds", [])
    return {f["name"]: f["url"] for f in feeds if isinstance(f, dict) and f.get("name") and f.get("url")}


def lire_systeme(client, flux: dict) -> dict:
    """Télécharge et interprète un système GBFS. Lève une exception en cas d'échec."""
    decouverte = client.get_json(flux["url"])
    urls = lire_decouverte(decouverte)
    if not urls:
        raise ValueError("fichier de découverte gbfs.json sans flux")

    nom = flux["jeu"]
    if "system_information" in urls:
        try:
            nom = _texte((client.get_json(urls["system_information"]).get("data") or {}).get("name")) or nom
        except Exception:
            pass  # le nom est secondaire

    # Types de véhicules : quels identifiants correspondent à des vélos ?
    ids_velo: set[str] | None = None
    if "vehicle_types" in urls:
        types = (client.get_json(urls["vehicle_types"]).get("data") or {}).get("vehicle_types") or []
        ids_velo = {str(t.get("vehicle_type_id")) for t in types
                    if str(t.get("form_factor", "")).lower() in FORMES_VELO}
        if types and not ids_velo:
            return {"nom": nom, "exclu": "aucun vélo (trottinettes, voitures ou autres)",
                    "stations": [], "libres": []}
    elif _contient(flux["jeu"], ("trottinette", "scooter")):
        return {"nom": nom, "exclu": "jeu de trottinettes", "stations": [], "libres": []}

    stations = []
    if "station_information" in urls:
        infos = (client.get_json(urls["station_information"]).get("data") or {}).get("stations") or []
        statuts = {}
        if "station_status" in urls:
            try:
                for s in (client.get_json(urls["station_status"]).get("data") or {}).get("stations") or []:
                    statuts[str(s.get("station_id"))] = s
            except Exception:
                statuts = {}  # positions sans disponibilités : on garde les stations
        for s in infos:
            try:
                lat, lon = float(s["lat"]), float(s["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            statut = statuts.get(str(s.get("station_id")))
            velos = None
            if statut is not None:
                if statut.get("is_installed") in (False, 0):
                    continue
                dispo_types = statut.get("vehicle_types_available")
                if ids_velo is not None and isinstance(dispo_types, list) and dispo_types:
                    lignes_velo = [d for d in dispo_types if str(d.get("vehicle_type_id")) in ids_velo]
                    if not lignes_velo:
                        continue  # station sans aucun vélo (ex. trottinettes seules)
                    velos = sum(int(d.get("count") or 0) for d in lignes_velo)
                else:
                    brut = statut.get("num_bikes_available", statut.get("num_vehicles_available"))
                    velos = int(brut) if isinstance(brut, (int, float)) else None
            stations.append({"lat": lat, "lon": lon, "nom": _texte(s.get("name")), "velos": velos})

    libres = []
    url_libres = urls.get("vehicle_status") or urls.get("free_bike_status")
    if url_libres:
        data = client.get_json(url_libres).get("data") or {}
        for v in data.get("vehicles") or data.get("bikes") or []:
            if v.get("station_id"):
                continue  # vélo garé en station : déjà compté dans station_status
            if v.get("is_disabled") in (True, 1) or v.get("is_reserved") in (True, 1):
                continue
            if ids_velo is not None and v.get("vehicle_type_id") is not None \
                    and str(v["vehicle_type_id"]) not in ids_velo:
                continue
            try:
                libres.append((float(v["lon"]), float(v["lat"])))
            except (KeyError, TypeError, ValueError):
                continue

    return {"nom": nom, "exclu": None, "stations": stations, "libres": libres}


# --------------------------------------------------------------------------
# 3. Agrégation par département
# --------------------------------------------------------------------------

def calculer(client, localisateur, codes_valides: set[str], travailleurs: int = 12) -> dict:
    flux = lister_flux(client)
    if not flux:
        raise ValueError("Aucun flux GBFS trouvé sur transport.data.gouv.fr")

    def essayer(f):
        try:
            return f, lire_systeme(client, f), None
        except Exception as e:  # un flux en panne ne doit pas tout bloquer
            return f, None, f"{type(e).__name__}: {e}"[:200]

    with ThreadPoolExecutor(max_workers=travailleurs) as pool:
        resultats = list(pool.map(essayer, flux))

    par_dep = {code: {"stations": 0, "velos": 0} for code in codes_valides}
    stations_carte, systemes, vues = [], [], set()
    journal = {"flux": len(flux), "ok": 0, "exclus": 0, "echecs": 0, "erreurs": []}

    for f, sysm, erreur in resultats:
        if erreur:
            journal["echecs"] += 1
            journal["erreurs"].append({"flux": f["jeu"], "url": f["url"], "erreur": erreur})
            continue
        if sysm["exclu"]:
            journal["exclus"] += 1
            continue
        journal["ok"] += 1
        i_sys = len(systemes)
        systemes.append(sysm["nom"])
        for s in sysm["stations"]:
            cle = (round(s["lat"], 5), round(s["lon"], 5))
            if cle in vues:   # même station publiée par deux flux
                continue
            vues.add(cle)
            dep = localisateur.trouver(s["lon"], s["lat"])
            if dep not in par_dep:
                continue  # hors métropole ou coordonnées aberrantes
            par_dep[dep]["stations"] += 1
            par_dep[dep]["velos"] += s["velos"] or 0
            stations_carte.append([round(s["lat"], 5), round(s["lon"], 5), s["nom"], s["velos"], i_sys])
        for lon, lat in sysm["libres"]:
            dep = localisateur.trouver(lon, lat)
            if dep in par_dep:
                par_dep[dep]["velos"] += 1

    if journal["ok"] == 0:
        raise ValueError(f"Aucun système VLS lisible ({journal['echecs']} échecs)")
    return {"par_dep": par_dep, "carte": {"systemes": systemes, "stations": stations_carte},
            "journal": journal}
