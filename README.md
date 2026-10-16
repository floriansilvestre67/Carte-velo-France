# Carte Vélo France

Carte interactive des départements de France métropolitaine montrant où le vélo est le mieux servi : linéaire d'aménagements cyclables, vélos en libre-service (VLS) et un « score vélo » sur 100. Toutes les données sont ouvertes et recalculées chaque jour.

Site : https://floriansilvestre67.github.io/Carte-velo-France/

## Comment ça marche

Le site est 100 % statique : des fichiers HTML, CSS et JavaScript, sans serveur ni base de données.

Chaque jour (et à chaque modification du code), GitHub Actions :

1. télécharge les sources de données sur les serveurs de GitHub ;
2. calcule les indicateurs par département avec le script Python `scripts/construire_donnees.py` ;
3. écrit trois fichiers légers dans `site/data/` ;
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

## Organisation du dépôt

```
.github/workflows/donnees-et-deploiement.yml   calcul des données et publication
scripts/
  construire_donnees.py   chef d'orchestre
  reseau.py               téléchargements (avec relances)
  indicateurs.py          ratios, rangs, score vélo
  sources/
    departements.py       contours des départements
    communes.py           population et surface
    amenagements.py       aménagements cyclables (lecture en streaming)
    vls.py                vélos en libre-service (GBFS 1.x, 2.x, 3.x)
tests/                    tests sur données fictives au format réel
site/
  index.html              la carte
  methode.html            page « Sources et méthode »
  css/style.css
  js/app.js, js/methode.js
  data/                   généré par GitHub Actions (non versionné)
```

## Sources de données

| Donnée | Source | Licence |
|---|---|---|
| Aménagements cyclables | [data.gouv.fr, jeu 60a37b7f303fdf4f2654b73d](https://www.data.gouv.fr/fr/datasets/amenagements-cyclables-france-metropolitaine/) (Geovelo, OSM) | ODbL |
| Vélos en libre-service | Flux GBFS de [transport.data.gouv.fr](https://transport.data.gouv.fr) | propre à chaque flux |
| Population, surface | [geo.api.gouv.fr](https://geo.api.gouv.fr) | Licence Ouverte |
| Contours | [gregoiredavid/france-geojson](https://github.com/gregoiredavid/france-geojson) | voir le dépôt |
| Fonds de carte | CARTO, CyclOSM, © contributeurs OpenStreetMap | ODbL |

La méthode de calcul (comptage des côtés, rangs centiles, score) est détaillée sur la page « Sources et méthode » du site.

## Travailler sur le code

```bash
pip install -r scripts/requirements.txt
python -m pytest -q tests                          # tests sans réseau
python scripts/construire_donnees.py --sortie site/data   # vraies données (≈ 10 min)
python -m http.server -d site 8000                 # puis http://localhost:8000
```

## Prochaines étapes

Niveau communes ou intercommunalités, stationnement vélo (OSM), véloroutes (Vélo & Territoires), compteurs vélo, outre-mer.
