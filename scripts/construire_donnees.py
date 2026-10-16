"""Génère les données du site : python scripts/construire_donnees.py --sortie site/data

Étapes :
  1. contours des départements   (indispensable : sans eux, on arrête tout)
  2. population et surface       (geo.api.gouv.fr)
  3. aménagements cyclables      (data.gouv.fr, schéma BNAC)
  4. vélos en libre-service      (flux GBFS de transport.data.gouv.fr)
  5. indicateurs, rangs et score vélo
  6. écriture de departements.geojson, stations.json et meta.json

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
from sources import amenagements, communes, departements, regions, vls

TAILLE_MAX = 50 * 1024 * 1024  # 50 Mo par fichier publié

CLES_AMENAGEMENTS = ["km_total"] + [f"km_{c}" for c in amenagements.CATEGORIES]
CLES_VLS = ["vls_stations", "vls_velos"]
CLES_COMMUNES = ["population", "surface_km2"]
CLES_REGIONS = ["region", "region_nom"]


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
    try:
        liste = communes.charger_communes(client)
        table_communes = communes.correspondance_commune_departement(liste)
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

    # 3. Aménagements
    journal("3/5 Aménagements cyclables (data.gouv.fr)…")
    try:
        res = amenagements.calculer(client, travail, table_communes, localisateur, codes)
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
    journal("4/5 Vélos en libre-service (GBFS)…")
    stations_carte = {"systemes": [], "stations": []}
    try:
        res = vls.calculer(client, localisateur, codes)
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

    # 5. Indicateurs
    journal("5/5 Indicateurs et score…")
    liste_props = indicateurs.calculer([props[d["code"]] for d in deps])
    par_code = {p["code"]: p for p in liste_props}

    geojson = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": par_code[d["code"]], "geometry": d["geometrie"]} for d in deps]}
    meta = {"genere_le": maintenant, "sources": sources_meta,
            "indicateurs": indicateurs.INDICATEURS, "score_indicateurs": indicateurs.SCORE_INDICATEURS}

    fichiers = {"departements.geojson": geojson, "stations.json": stations_carte, "meta.json": meta}
    for nom, contenu in fichiers.items():
        chemin = sortie / nom
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(contenu, f, ensure_ascii=False, separators=(",", ":"))
        taille = chemin.stat().st_size
        journal(f"  → {chemin} ({taille / 1024:.0f} Ko)")
        if taille > TAILLE_MAX:
            raise RuntimeError(f"{nom} dépasse 50 Mo ({taille / 1e6:.1f} Mo)")
    return meta


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
