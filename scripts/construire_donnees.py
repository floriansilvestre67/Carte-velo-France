"""Génère les données du site : python scripts/construire_donnees.py --sortie site/data

Étapes :
  1. contours des départements   (indispensable : sans eux, on arrête tout)
  2. population et surface       (geo.api.gouv.fr)
  3. aménagements cyclables      (data.gouv.fr, schéma BNAC)
  4. vélos en libre-service      (flux GBFS de transport.data.gouv.fr)
  5. accidents de vélo            (Koumoul / ONISR)
  6. indicateurs, rangs et score vélo
  7. écriture des fichiers : departements.geojson, stations.json, meta.json,
     accidents/national.json et communes/{département}.json

Si une source (2, 3 ou 4) est en panne, on reprend ses chiffres dans la version
déjà publiée du site (SITE_PRECEDENT_URL) ; s'il n'y en a pas, la donnée est
marquée « indisponible ». Aucun chiffre n'est jamais inventé.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

import indicateurs
from reseau import ClientHTTP
from sources import (accidents, amenagements, communes, contours_communes, departements, poi, regions,
                     stationnement, vls)

TAILLE_MAX = 50 * 1024 * 1024  # 50 Mo par fichier publié

CLES_AMENAGEMENTS = ["km_total"] + [f"km_{c}" for c in amenagements.CATEGORIES]
CLES_VLS = ["vls_stations", "vls_velos"]
CLES_COMMUNES = ["population", "surface_km2"]
CLES_REGIONS = ["region", "region_nom"]
CLES_STATIONNEMENT = ["stat_places", "stat_places_secu", "stat_secu_1000"]
POI_JOURS = 7  # les points d'intérêt (≈ 450 Mo de sources) ne sont recalculés qu'une fois par semaine
SEUIL_GRANDES_COMMUNES = 10_000  # habitants : communes retenues pour les corrélations nationales


def journal(message: str) -> None:
    print(message, flush=True)


def charger_precedent(client, url_base: str | None) -> dict | None:
    """Récupère les données actuellement en ligne, pour servir de secours."""
    if not url_base:
        return None
    base = url_base.rstrip("/") + "/data/"
    try:
        geo = client.get_json(base + "departements.geojson")
        meta = client.get_json(base + "meta.json")
    except Exception:
        journal("  (pas de version précédente en ligne : premier déploiement ?)")
        return None
    precedent = {"props": {f["properties"]["code"]: f["properties"] for f in geo.get("features", [])},
                 "meta": meta, "stations": None}
    try:
        precedent["stations"] = client.get_json(base + "stations.json")
    except Exception:
        pass
    return precedent


def ecrire_json(chemin: Path, contenu) -> int:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(contenu, f, ensure_ascii=False, separators=(",", ":"))
    taille = chemin.stat().st_size
    if taille > TAILLE_MAX:
        raise RuntimeError(f"{chemin.name} dépasse 50 Mo ({taille / 1e6:.1f} Mo)")
    return taille


def fichier_precedent(client, url_base: str | None, chemin_relatif: str):
    """Un fichier de données de la version en ligne, ou None."""
    if not url_base:
        return None
    try:
        return client.get_json(url_base.rstrip("/") + "/data/" + chemin_relatif)
    except Exception:
        return None


def reprendre(precedent, cles, nom_source):
    """Valeurs de la version précédente pour ces clés, avec la date d'origine."""
    if not precedent:
        return None, None
    valeurs = {code: {c: p.get(c) for c in cles} for code, p in precedent["props"].items()}
    ancienne = (precedent["meta"].get("sources") or {}).get(nom_source) or {}
    return valeurs, ancienne


def construire(client, sortie: Path, travail: Path, url_precedent: str | None = None) -> dict:
    sortie.mkdir(parents=True, exist_ok=True)
    maintenant = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sources_meta: dict[str, dict] = {}

    journal("1/5 Contours des départements…")
    deps = departements.charger_contours(client)
    codes = {d["code"] for d in deps}
    localisateur = departements.LocalisateurDepartement(deps)
    sources_meta["contours"] = {"statut": "ok", "url": departements.URL_CONTOURS,
                                "detail": f"{len(deps)} départements"}
    journal(f"  {len(deps)} départements")

    precedent = charger_precedent(client, url_precedent)
    props = {d["code"]: {"code": d["code"], "nom": d["nom"]} for d in deps}

    def appliquer_secours(nom_source, cles, erreur):
        valeurs, ancienne = reprendre(precedent, cles, nom_source)
        if valeurs and ancienne and ancienne.get("statut") in ("ok", "reprise"):
            for code in codes:
                for c in cles:
                    props[code][c] = (valeurs.get(code) or {}).get(c)
            sources_meta[nom_source] = {**ancienne, "statut": "reprise",
                                        "detail": f"Source injoignable aujourd'hui ({erreur}). "
                                                  f"Chiffres repris de la mise à jour précédente."}
            journal(f"  ⚠ reprise des chiffres précédents")
            return True
        for code in codes:
            for c in cles:
                props[code][c] = None
        sources_meta[nom_source] = {"statut": "indisponible", "detail": f"Source injoignable : {erreur}"}
        journal(f"  ⚠ donnée indisponible")
        return False

    # 2. Communes
    journal("2/5 Population et surface (geo.api.gouv.fr)…")
    table_communes: dict[str, str] = {}
    liste_communes: list[dict] = []
    arrondissements: list[dict] = []
    correspondance = None
    try:
        liste = communes.charger_communes(client)
        liste_communes = liste
        table_communes = communes.correspondance_commune_departement(liste)
        anciennes = communes.charger_anciennes(client)
        try:
            arrondissements = client.get_json(communes.URL_ARRONDISSEMENTS) or []
        except Exception:
            arrondissements = []
        correspondance = communes.Correspondance(liste, anciennes)
        journal(f"  {len(liste)} communes, {len(anciennes)} anciennes communes rattachées")
        agg = communes.agreger_par_departement(liste)
        for code in codes:
            a = agg.get(code) or {}
            props[code]["population"] = a.get("population") or None
            props[code]["surface_km2"] = round(a["surface_km2"], 1) if a.get("surface_km2") else None
        sources_meta["communes"] = {"statut": "ok", "url": communes.URL_COMMUNES,
                                    "date_donnees": maintenant[:10],
                                    "detail": f"{len(liste)} communes"}
    except Exception as e:
        journal(f"  ✗ {e}")
        appliquer_secours("communes", CLES_COMMUNES, e)

    # 2 bis. Régions (pour le filtre régional du site)
    journal("   Régions (geo.api.gouv.fr)…")
    try:
        table_regions = regions.charger(client)
        for code in codes:
            r = table_regions.get(code) or {}
            props[code]["region"] = r.get("region")
            props[code]["region_nom"] = r.get("region_nom")
        sources_meta["regions"] = {"statut": "ok", "url": regions.URL_DEPARTEMENTS,
                                   "detail": f"{len({r['region'] for r in table_regions.values()})} régions"}
    except Exception as e:
        journal(f"  ✗ {e}")
        appliquer_secours("regions", CLES_REGIONS, e)

    # 2 ter. Contours des communes (recherche de ville, rattachement des points)
    journal("   Contours des communes (Etalab)…")
    contours_par_dep, localisateur_communes = None, None
    try:
        res_c = contours_communes.calculer(client, travail, codes)
        contours_par_dep = res_c["par_dep"]
        sources_meta["contours_communes"] = {"statut": "ok", "url": contours_communes.URL_CONTOURS,
                                             "detail": f"{res_c['diagnostic']['communes']} communes",
                                             "diagnostic": res_c["diagnostic"]}
        journal(f"  {res_c['diagnostic']}")
    except Exception as e:
        journal(f"  ✗ {e}")
        anciens = {dep: fichier_precedent(client, url_precedent, f"contours/{dep}.geojson") for dep in codes}
        if all(anciens.values()):
            contours_par_dep = {dep: f.get("features", []) for dep, f in anciens.items()}
            sources_meta["contours_communes"] = {"statut": "reprise", "url": contours_communes.URL_CONTOURS,
                                                 "detail": f"Source injoignable ({e}) : contours repris de la veille."}
        else:
            sources_meta["contours_communes"] = {"statut": "indisponible", "detail": f"Source injoignable : {e}"}
    if contours_par_dep:
        localisateur_communes = contours_communes.LocalisateurCommune(contours_par_dep)

    # 3. Aménagements
    km_communes: dict[str, dict] | None = None
    journal("3/5 Aménagements cyclables (data.gouv.fr)…")
    try:
        res = amenagements.calculer(client, travail, table_communes, localisateur, codes, correspondance)
        km_communes = res["km_communes"]
        for code in codes:
            km = res["km"][code]
            for cat in amenagements.CATEGORIES:
                props[code][f"km_{cat}"] = round(km[cat], 2)
            props[code]["km_total"] = round(sum(km.values()), 2)
        st = res["stats"]
        sources_meta["amenagements"] = {
            "statut": "ok", "url": res["ressource"]["url"], "titre": res["ressource"]["titre"],
            "date_donnees": res["ressource"]["publiee_le"] or st["date_maj_max"],
            "detail": f"{st['troncons']:,} tronçons lus".replace(",", " "),
            # Kilomètres par valeur brute du schéma (pour vérifier le classement par catégorie)
            "km_par_type": {k: round(v) for k, v in sorted(st["km_par_type_brut"].items(),
                                                           key=lambda kv: -kv[1])},
        }
        journal(f"  {st['troncons']} tronçons, {st['troncons_sans_departement']} côtés sans département, "
                f"{st['km_hors_metropole']:.0f} km hors métropole ignorés")
    except Exception as e:
        journal(f"  ✗ {e}")
        traceback.print_exc()
        appliquer_secours("amenagements", CLES_AMENAGEMENTS, e)

    # 4. VLS
    vls_communes: dict[str, dict] | None = None
    journal("4/5 Vélos en libre-service (GBFS)…")
    stations_carte = {"systemes": [], "stations": []}
    try:
        res = vls.calculer(client, localisateur, codes, localisateur_communes=localisateur_communes)
        vls_communes = res["par_commune"] if localisateur_communes is not None else None
        for code in codes:
            props[code]["vls_stations"] = res["par_dep"][code]["stations"]
            props[code]["vls_velos"] = res["par_dep"][code]["velos"]
        stations_carte = res["carte"]
        j = res["journal"]
        sources_meta["vls"] = {"statut": "ok", "url": vls.URL_API_JEUX, "date_donnees": maintenant[:10],
                               "detail": f"{j['ok']} systèmes lus ({j['jeux']} jeux de données ; "
                                         f"{j['exclus']} sans vélo écartés, {j['doublons']} doublons, "
                                         f"{j['echecs']} en échec)",
                               "erreurs": j["erreurs"][:50]}
        journal(f"  {j['ok']} systèmes OK, {j['exclus']} exclus, {j['doublons']} doublons, {j['echecs']} en échec, "
                f"{len(stations_carte['stations'])} stations")
        for err in j["erreurs"][:30]:
            journal(f"    - {err['jeu']} : {err['erreur']}")
    except Exception as e:
        journal(f"  ✗ {e}")
        if appliquer_secours("vls", CLES_VLS, e) and precedent and precedent.get("stations"):
            stations_carte = precedent["stations"]

    # 4 bis. Stationnement vélo
    journal("   Stationnement vélo (indicateurs Ecolab et emplacements OSM)…")
    stat_communes, emplacements_osm = None, None
    try:
        ind = stationnement.indicateurs(client, travail)
        dep_ind = ind["departement"]
        for code in codes:
            pl = dep_ind["places"].get(code)
            props[code]["stat_places"] = round(pl["places"]) if pl else None
            props[code]["stat_places_secu"] = round(pl["places_secu"]) if pl else None
            v = dep_ind["secu_1000"].get(code)
            props[code]["stat_secu_1000"] = round(v, 3) if v is not None else None
        com = ind["commune"]
        stat_communes = {c: {"p": round(v["places"]), "s": round(v["places_secu"])} for c, v in com["places"].items()}
        for c, v in com["secu_1000"].items():
            stat_communes.setdefault(c, {})["s1000"] = round(v, 2)
        sources_meta["stationnement"] = {
            "statut": "ok", "url": "https://www.data.gouv.fr/datasets/nombre-de-places-de-stationnement-velo",
            "date_donnees": dep_ind["date_places"],
            "detail": f"Relevé au {dep_ind['date_places']} ; {len(stat_communes)} communes renseignées"}
        journal(f"  {sources_meta['stationnement']['detail']}")
    except Exception as e:
        journal(f"  ✗ indicateurs : {e}")
        traceback.print_exc()
        appliquer_secours("stationnement", CLES_STATIONNEMENT, e)
    try:
        emplacements_osm = stationnement.emplacements(client, travail, codes, localisateur)
        st = emplacements_osm["stats"]
        meta_osm = {"statut": "ok", "url": emplacements_osm["url"], "date_donnees": maintenant[:10],
                    "detail": f"{st['points']:,} emplacements ; {st['sans_capacite']:,} sans capacité renseignée".replace(",", " ")}
        if sources_meta.get("stationnement", {}).get("statut") == "ok":
            officiel = {c: {"places": props[c]["stat_places"] or 0} for c in codes}
            meta_osm["coherence"] = stationnement.coherence(st["places"], officiel)
        sources_meta["stationnement_osm"] = meta_osm
        journal(f"  {meta_osm['detail']} ; cohérence : {meta_osm.get('coherence', {}).get('ecart_pct')} %")
    except Exception as e:
        journal(f"  ✗ emplacements : {e}")
        traceback.print_exc()
        sources_meta["stationnement_osm"] = {"statut": "indisponible", "detail": f"Source injoignable : {e}"}

    # 4 ter. Points d'intérêt
    journal("   Points d'intérêt (DATAtourisme, Mérimée, Muséofile)…")
    poi_par_dep = None
    ancien_poi = ((precedent or {}).get("meta", {}).get("sources") or {}).get("poi") or {}
    age = None
    if ancien_poi.get("date_donnees") and ancien_poi.get("statut") == "ok" and ancien_poi.get("version") == poi.VERSION:
        age = (datetime.fromisoformat(maintenant[:10]) - datetime.fromisoformat(ancien_poi["date_donnees"])).days
    if age is not None and age < POI_JOURS and not os.environ.get("FORCER_POI"):
        anciens = {dep: fichier_precedent(client, url_precedent, f"poi/{dep}.json") for dep in codes}
        if all(anciens.values()):
            poi_par_dep = {dep: f["points"] for dep, f in anciens.items()}
            sources_meta["poi"] = ancien_poi
            journal(f"  recalcul hebdomadaire : fichiers du {ancien_poi['date_donnees']} repris")
    if poi_par_dep is None:
        try:
            res_p = poi.calculer(client, travail, codes, localisateur, localisateur_communes)
            poi_par_dep = res_p["par_dep"]
            st = res_p["stats"]
            sources_meta["poi"] = {
                "statut": "ok", "url": "https://www.data.gouv.fr/datasets/" + poi.ID_DATATOURISME, "version": poi.VERSION,
                "date_donnees": maintenant[:10],
                "detail": (f"{sum(res_p['comptes'].values()):_} lieux retenus, dont {st.get('officiels_lus', 0):_} monuments "
                           f"et musées officiels lus ; {st.get('doublons', 0):_} doublons fusionnés").replace("_", " ")
                          + (" ; sources en échec : " + ", ".join(res_p["erreurs"]) if res_p["erreurs"] else ""),
                "comptes": res_p["comptes"], "classes_gardees": st.get("classes_gardees"),
                "diagnostic": {"merimee_lignes": st.get("merimee_lignes"), "museofile_lignes": st.get("museofile_lignes"),
                               "fichiers": st.get("fichiers")},
                "classes_ecartees": st.get("classes_ecartees")}
            journal(f"  {sources_meta['poi']['detail']} {res_p['comptes']}")
        except Exception as e:
            journal(f"  ✗ {e}")
            traceback.print_exc()
            anciens = {dep: fichier_precedent(client, url_precedent, f"poi/{dep}.json") for dep in codes}
            if all(anciens.values()):
                poi_par_dep = {dep: f["points"] for dep, f in anciens.items()}
                sources_meta["poi"] = {**ancien_poi, "statut": "reprise",
                                       "detail": f"Sources injoignables ({e}) : lieux repris de la mise à jour précédente."}
            else:
                sources_meta["poi"] = {"statut": "indisponible", "detail": f"Sources injoignables : {e}"}

    # 5. Accidents de vélo
    journal("5/6 Accidents de vélo (Koumoul / ONISR)…")
    accs = None
    try:
        info = accidents.metadonnees(client)
        res_acc = accidents.construire_accidents(accidents.lire_lignes(client), codes, correspondance)
        accs = res_acc["accidents"]
        st = res_acc["stats"]
        annees = sorted({a["an"] for a in accs})
        sources_meta["accidents"] = {
            "statut": "ok", "url": accidents.URL_PAGE_JEU, "date_donnees": info["maj"],
            "annees": [annees[0], annees[-1]],
            "detail": f"{st['accidents']:,} accidents ({st['lignes']:,} cyclistes) de {annees[0]} à {annees[-1]} ; "
                      f"{st.get('lignes_hors_metropole', 0):,} lignes hors métropole écartées".replace(",", " ")}
        journal(f"  {st}")
    except Exception as e:
        journal(f"  ✗ {e}")
        traceback.print_exc()

    # 6. Indicateurs
    journal("6/6 Indicateurs et score…")
    liste_props = indicateurs.calculer([props[d["code"]] for d in deps])
    par_code = {p["code"]: p for p in liste_props}
    region_de = {c: p.get("region") for c, p in par_code.items()}

    ecrire_accidents_et_communes(client, sortie, url_precedent, sources_meta, deps, par_code, region_de,
                                 liste_communes, correspondance, km_communes, accs, vls_communes, stat_communes)
    ecrire_stationnement(client, sortie, url_precedent, codes, emplacements_osm, sources_meta)
    if poi_par_dep is not None:
        total = 0
        for dep in codes:
            total += ecrire_json(sortie / "poi" / f"{dep}.json", {
                "categories": poi.CATEGORIES, "sources": poi.SOURCES, "champs": poi.CHAMPS,
                "points": poi_par_dep.get(dep, [])})
        journal(f"  → poi/*.json ({total / 1024:.0f} Ko au total)")
    ecrire_communes_carte(client, sortie, url_precedent, codes, liste_communes, arrondissements, contours_par_dep)

    geojson = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": par_code[d["code"]], "geometry": d["geometrie"]} for d in deps]}
    meta = {"genere_le": maintenant, "sources": sources_meta,
            "indicateurs": indicateurs.INDICATEURS, "score_indicateurs": indicateurs.SCORE_INDICATEURS}

    fichiers = {"departements.geojson": geojson, "stations.json": stations_carte, "meta.json": meta}
    for nom, contenu in fichiers.items():
        taille = ecrire_json(sortie / nom, contenu)
        journal(f"  → {sortie / nom} ({taille / 1024:.0f} Ko)")
    return meta


def ecrire_stationnement(client, sortie, url_precedent, codes, emplacements_osm, sources_meta) -> None:
    """stationnement/{dep}.json : emplacements OSM du département (calque de la carte)."""
    total = 0
    if emplacements_osm:
        for dep in codes:
            contenu = {"champs": stationnement.CHAMPS_POINT, "valeurs": emplacements_osm["valeurs"],
                       "points": emplacements_osm["par_dep"].get(dep, [])}
            total += ecrire_json(sortie / "stationnement" / f"{dep}.json", contenu)
    else:
        anciens = {dep: fichier_precedent(client, url_precedent, f"stationnement/{dep}.json") for dep in codes}
        if not any(anciens.values()):
            return
        for dep, contenu in anciens.items():
            if contenu:
                total += ecrire_json(sortie / "stationnement" / f"{dep}.json", contenu)
        sources_meta["stationnement_osm"]["statut"] = "reprise"
        sources_meta["stationnement_osm"]["detail"] += " Emplacements repris de la mise à jour précédente."
    journal(f"  → stationnement/*.json ({total / 1024:.0f} Ko au total)")


def ecrire_communes_carte(client, sortie, url_precedent, codes, liste_communes, arrondissements,
                          contours_par_dep) -> None:
    """communes-index.json (recherche de ville) et contours/{dep}.geojson."""
    if liste_communes:
        index = communes.index_recherche(liste_communes, arrondissements, set(codes))
    else:
        index = fichier_precedent(client, url_precedent, "communes-index.json")
    if index:
        taille = ecrire_json(sortie / "communes-index.json", index)
        journal(f"  → communes-index.json ({taille / 1024:.0f} Ko)")
    if contours_par_dep:
        total = 0
        for dep in codes:
            total += ecrire_json(sortie / "contours" / f"{dep}.geojson",
                                 {"type": "FeatureCollection", "features": contours_par_dep.get(dep, [])})
        journal(f"  → contours/*.geojson ({total / 1024:.0f} Ko au total)")


def ecrire_accidents_et_communes(client, sortie, url_precedent, sources_meta, deps, par_code, region_de,
                                 liste_communes, correspondance, km_communes, accs, vls_communes=None,
                                 stat_communes=None) -> None:
    """Écrit accidents/national.json et communes/{dep}.json.

    Chaque composante manquante aujourd'hui (liste des communes, km par commune,
    accidents) est reprise de la version en ligne si elle existe.
    """
    codes = [d["code"] for d in deps]

    # --- Communes : nom, population, surface, km d'aménagements ---
    par_dep: dict[str, dict] = {c: {} for c in codes}
    for c in liste_communes:
        dep = c.get("codeDepartement")
        if dep in par_dep:
            par_dep[dep][c["code"]] = {
                "n": c.get("nom"), "p": c.get("population"),
                "s": round(c["surface"] / 100, 2) if isinstance(c.get("surface"), (int, float)) else None}
    if km_communes is not None:
        for code_com, km in km_communes.items():
            dep = correspondance.departement(code_com) if correspondance else None
            if dep in par_dep and code_com in par_dep[dep]:
                par_dep[dep][code_com]["km"] = {k: round(v, 2) for k, v in km.items() if v}
                par_dep[dep][code_com]["km"]["t"] = round(sum(km.values()), 2)
        # Communes sans aucun aménagement recensé : 0 km (et non « indisponible »)
        for dep in par_dep:
            for fiche in par_dep[dep].values():
                fiche.setdefault("km", {"t": 0})

    precedents: dict[str, dict] = {}

    def precedent_dep(dep):
        if dep not in precedents:
            precedents[dep] = fichier_precedent(client, url_precedent, f"communes/{dep}.json") or {}
        return precedents[dep]

    # --- Accidents ---
    national = None
    if accs:
        agg = accidents.agreger(accs, region_de)
        annees = agg["annees"]
        par_commune = accidents.compter_par_commune(accs, correspondance, annees)
        national = {"annees": annees,
                    "libelles": {"gravite": accidents.GRAVITES, "vehicule": accidents.VEHICULES,
                                 "trajet": accidents.TRAJETS, "situ": accidents.SITUATIONS},
                    "ruptures": accidents.RUPTURES, "zones": agg["zones"]}
    else:
        national = fichier_precedent(client, url_precedent, "accidents/national.json")
        if national:
            ancienne = sources_meta.get("accidents") or {}
            sources_meta["accidents"] = {**ancienne, "statut": "reprise",
                                         "detail": "Source injoignable aujourd'hui : chiffres repris de la "
                                                   "mise à jour précédente."}
        else:
            sources_meta["accidents"] = {"statut": "indisponible", "detail": "Source injoignable."}

    # --- Fichiers par département ---
    total = 0
    for dep in codes:
        communes_dep = par_dep[dep]
        ancien = None
        if not communes_dep:                          # geo.api en panne
            ancien = precedent_dep(dep)
            communes_dep = ancien.get("communes") or {}
        elif km_communes is None:                      # aménagements en panne
            ancien = precedent_dep(dep)
            for code_com, fiche in communes_dep.items():
                km = ((ancien.get("communes") or {}).get(code_com) or {}).get("km")
                if km is not None:
                    fiche["km"] = km
        # Stationnement (indicateurs officiels) : p places, s sécurisées, s1000 sécurisées / 1 000 hab.
        if stat_communes is not None:
            for code_com, fiche in communes_dep.items():
                if code_com in stat_communes:
                    fiche["stat"] = stat_communes[code_com]
        else:
            ancien_stat = (precedent_dep(dep).get("communes") or {})
            for code_com, fiche in communes_dep.items():
                if (ancien_stat.get(code_com) or {}).get("stat") is not None:
                    fiche["stat"] = ancien_stat[code_com]["stat"]
        # Vélos en libre-service par commune (st : stations, zv : zones virtuelles, v : vélos)
        if vls_communes is not None:
            for code_com, fiche in communes_dep.items():
                fiche["vls"] = vls_communes.get(code_com) or {"st": 0, "zv": 0, "v": 0}
        else:
            ancien_vls = (precedent_dep(dep).get("communes") or {})
            for code_com, fiche in communes_dep.items():
                if (ancien_vls.get(code_com) or {}).get("vls") is not None:
                    fiche["vls"] = ancien_vls[code_com]["vls"]
        if accs:
            lignes = [accidents.enregistrement(a, correspondance) for a in accs if a["dep"] == dep]
        else:
            lignes = ((precedent_dep(dep).get("accidents") or {}).get("lignes")) or []
        contenu = {"dep": dep, "communes": communes_dep,
                   "accidents": {"champs": accidents.CHAMPS_ENREGISTREMENT, "lignes": lignes}}
        total += ecrire_json(sortie / "communes" / f"{dep}.json", contenu)
    journal(f"  → communes/*.json ({total / 1024:.0f} Ko au total)")

    if not national:
        return

    # Informations par zone pour les ratios (population et km actuels)
    def somme(cles, cle):
        vals = [par_code[c].get(cle) for c in cles]
        return None if any(v is None for v in vals) else round(sum(vals), 2)

    infos = {"FR": {"nom": "France métropolitaine", "pop": somme(codes, "population"),
                    "km": somme(codes, "km_total")}}
    for c in codes:
        p = par_code[c]
        infos["D" + c] = {"nom": p["nom"], "pop": p.get("population"), "km": p.get("km_total"),
                          "parent": "R" + p["region"] if p.get("region") else None}
    regions_vues = {}
    for c in codes:
        if par_code[c].get("region"):
            regions_vues.setdefault(par_code[c]["region"], {"nom": par_code[c]["region_nom"], "deps": []})["deps"].append(c)
    for r, v in regions_vues.items():
        infos["R" + r] = {"nom": v["nom"], "pop": somme(v["deps"], "population"), "km": somme(v["deps"], "km_total")}
    national["zones_info"] = infos

    # Grandes communes (corrélations) : population, km et accidents par année
    if accs and liste_communes:
        grandes = {}
        for dep in codes:
            for code_com, fiche in par_dep[dep].items():
                if (fiche.get("p") or 0) < SEUIL_GRANDES_COMMUNES:
                    continue
                cpt = par_commune.get(code_com) or {"acc": [0] * len(national["annees"]),
                                                    "tues": [0] * len(national["annees"]),
                                                    "blesses": [0] * len(national["annees"])}
                grandes[code_com] = {"n": fiche["n"], "d": dep, "p": fiche["p"],
                                     "km": (fiche.get("km") or {}).get("t"), **cpt}
        national["grandes_communes"] = grandes
    else:
        ancien = fichier_precedent(client, url_precedent, "accidents/national.json") or {}
        national["grandes_communes"] = national.get("grandes_communes") or ancien.get("grandes_communes") or {}

    taille = ecrire_json(sortie / "accidents" / "national.json", national)
    journal(f"  → accidents/national.json ({taille / 1024:.0f} Ko)")


def resume_github(meta: dict) -> None:
    """Petit tableau récapitulatif affiché sur la page du run GitHub Actions."""
    chemin = os.environ.get("GITHUB_STEP_SUMMARY")
    if not chemin:
        return
    icones = {"ok": "✅", "reprise": "⚠️", "indisponible": "❌"}
    lignes = ["## Données générées", "", "| Source | Statut | Détail |", "|---|---|---|"]
    for nom, s in meta["sources"].items():
        detail = str(s.get("detail", "")).replace("|", "/")
        lignes.append(f"| {nom} | {icones.get(s['statut'], '')} {s['statut']} | {detail} |")
    with open(chemin, "a", encoding="utf-8") as f:
        f.write("\n".join(lignes) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sortie", type=Path, default=Path("site/data"))
    parser.add_argument("--precedent", default=os.environ.get("SITE_PRECEDENT_URL"),
                        help="URL du site déjà publié, pour reprendre une source en panne")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as travail:
        meta = construire(ClientHTTP(), args.sortie, Path(travail), args.precedent)
    resume_github(meta)
    journal("Terminé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
