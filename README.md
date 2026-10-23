# Carte Vélo France

Carte interactive de la France métropolitaine montrant où le vélo est le mieux servi : aménagements cyclables, vélos en libre-service (VLS), stationnement vélo, lieux à visiter, accidents de vélo et un « score vélo » sur 100. On peut descendre au niveau de chaque ville. Toutes les données sont ouvertes et recalculées chaque jour.

- **Carte** : départements colorés selon l'indicateur choisi, filtre par région, recherche de ville (nom ou code postal) avec fiche détaillée, calques des stations VLS, du stationnement, des lieux à visiter et des pistes CyclOSM.
- **Statistiques** : accidents de vélo par zone (France, région, département, ville) et par période, avec graphiques, ratios et corrélations.
- **Sources et méthode** : origine de chaque donnée, définitions, limites et état du dernier calcul.

Une ville se partage par son code INSEE dans l'adresse, sur les deux pages : `?ville=63113`.

Site : https://floriansilvestre67.github.io/Carte-velo-France/

## Comment ça marche

Le site est 100 % statique : des fichiers HTML, CSS et JavaScript, sans serveur ni base de données.

Chaque jour (et à chaque modification du code), GitHub Actions :

1. télécharge les sources de données sur les serveurs de GitHub ;
2. calcule les indicateurs avec le script Python `scripts/construire_donnees.py` ;
3. écrit des fichiers JSON légers dans `site/data/` : un fichier national par thème, et les données détaillées découpées par département, chargées seulement quand on en a besoin ;
4. publie le dossier `site/` sur GitHub Pages.

Si une source est en panne un jour donné, le script reprend les chiffres de la veille depuis le site en ligne et le signale sur la page « Sources et méthode ». Aucun chiffre n'est inventé : une donnée absente s'affiche « indisponible ».

## Activer le site (à faire une seule fois)

1. Sur GitHub, ouvrez le dépôt puis **Settings** (Paramètres).
2. Dans le menu de gauche, cliquez sur **Pages**.
3. Sous **Build and deployment**, choisissez **Source : GitHub Actions**.
4. Ouvrez l'onglet **Actions**, cliquez sur **Données et déploiement** puis sur **Run workflow**.

Au bout de 5 à 15 minutes, le site est en ligne à l'adresse indiquée plus haut. Ensuite, tout est automatique.

## Suivre et dépanner

- Onglet **Actions** : chaque exécution affiche un tableau récapitulatif de l'état des sources.
- Une coche rouge signifie que l'exécution a échoué. Le site reste alors en ligne avec ses données précédentes. Cliquez sur l'exécution pour lire le journal, en français.
- Pour relancer à la main : **Actions > Données et déploiement > Run workflow**.
- Les fichiers d'accidents (environ 600 Mo) ne sont retraités que lorsqu'ils changent sur data.gouv.fr. Les lieux à visiter (plus de 400 Mo de sources) ne sont recalculés qu'une fois par semaine. Pour forcer leur mise à jour, cochez « Recalculer les points d'intérêt » dans la fenêtre **Run workflow**.

## Organisation du dépôt

```
.github/workflows/donnees-et-deploiement.yml   calcul des données et publication
scripts/
  construire_donnees.py   chef d'orchestre
  reseau.py               téléchargements (avec relances)
  indicateurs.py          ratios, rangs, score vélo
  sources/
    departements.py       contours des départements
    communes.py           communes : population, codes postaux, correspondance des codes
    contours_communes.py  contours des communes (Etalab), rattachement des points
    regions.py            région de chaque département
    amenagements.py       aménagements cyclables (lecture en streaming)
    vls.py                vélos en libre-service (GBFS 1.x, 2.x, 3.x)
    baac.py               fichiers officiels des accidents (BAAC, ONISR)
    accidents.py          accidents de vélo : regroupement, codes, agrégats
    stationnement.py      stationnement vélo (indicateurs Ecolab, emplacements OSM)
    poi.py                lieux à visiter (DATAtourisme, Mérimée, Muséofile)
tests/                    tests sur données fictives au format réel
site/
  index.html              la carte
  statistiques.html       la page Statistiques (accidents)
  methode.html            page « Sources et méthode »
  css/style.css, css/statistiques.css
  js/app.js               carte, fiche Ville, calques
  js/ville.js             recherche de ville (commune aux deux pages)
  js/statistiques.js      graphiques (Chart.js) et filtres
  js/methode.js
  data/                   généré par GitHub Actions (non versionné)
    departements.geojson, meta.json, stations.json, communes-index.json
    accidents/national.json
    communes/{dép}.json, contours/{dép}.geojson, stationnement/{dép}.json, poi/{dép}.json
```

## Sources de données

| Donnée | Source | Licence |
|---|---|---|
| Aménagements cyclables | [data.gouv.fr, jeu 60a37b7f303fdf4f2654b73d](https://www.data.gouv.fr/fr/datasets/amenagements-cyclables-france-metropolitaine/) (Geovelo, OSM) | ODbL |
| Vélos en libre-service | Flux GBFS de [transport.data.gouv.fr](https://transport.data.gouv.fr) | propre à chaque flux |
| Population, surface, régions | [geo.api.gouv.fr](https://geo.api.gouv.fr) | Licence Ouverte |
| Contours des départements | [gregoiredavid/france-geojson](https://github.com/gregoiredavid/france-geojson) | voir le dépôt |
| Contours des communes | [Etalab, contours administratifs](https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/latest/geojson/) | Licence Ouverte |
| Accidents de vélo | [Fichiers BAAC de l'ONISR](https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-routiere-annees-de-2005-a-2024/) (ministère de l'Intérieur) | Licence Ouverte |
| Stationnement (indicateurs) | [Ecolab, places de stationnement vélo](https://www.data.gouv.fr/datasets/nombre-de-places-de-stationnement-velo) et [places sécurisées](https://www.data.gouv.fr/datasets/nombre-de-places-de-stationnement-velo-securisees-type-accroche-cadre-et-roue-ou-cadre-pour-1000-hab) | ODbL |
| Lieux à visiter | [DATAtourisme](https://www.data.gouv.fr/datasets/5b598be088ee387c0c353714), [Monuments historiques (Mérimée)](https://www.data.gouv.fr/datasets/immeubles-proteges-au-titre-des-monuments-historiques-2), [Musées de France (Muséofile)](https://www.data.gouv.fr/datasets/musees-de-france-base-museofile) | Licence Ouverte |
| Stationnement (emplacements) | [Stationnements cyclables issus d'OpenStreetMap](https://www.data.gouv.fr/datasets/stationnements-cyclables-issus-dopenstreetmap) | ODbL |
| Fonds de carte | OpenStreetMap, CyclOSM, © contributeurs OpenStreetMap | ODbL |

La méthode de calcul (comptage des côtés, rangs centiles, score) est détaillée sur la page « Sources et méthode » du site.

## Travailler sur le code

```bash
pip install -r scripts/requirements.txt
python -m pytest -q tests                          # tests sans réseau
python scripts/construire_donnees.py --sortie site/data   # vraies données (≈ 15 min)
python -m http.server -d site 8000                 # puis http://localhost:8000
```

## Prochaines étapes

Véloroutes (Vélo & Territoires), compteurs vélo, intercommunalités, outre-mer.
