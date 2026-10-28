"""Accès réseau : téléchargements HTTP avec relances automatiques.

Toutes les sources passent par un objet « client ». En production c'est
ClientHTTP (requests). Dans les tests, on lui substitue un faux client qui
lit des fichiers locaux : le reste du code ne voit pas la différence.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

USER_AGENT = "carte-velo-france/1.0 (+https://github.com/floriansilvestre67/Carte-velo-France)"


class ErreurSource(Exception):
    """Une source de données est injoignable ou renvoie un format inattendu."""


class ClientHTTP:
    def __init__(self, delai: float = 30.0, relances: int = 3):
        self.delai = delai
        self.relances = relances
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def _get(self, url: str, **kwargs) -> requests.Response:
        derniere_erreur: Exception | None = None
        delai = kwargs.pop("timeout", None) or self.delai
        for essai in range(self.relances):
            try:
                rep = self.session.get(url, timeout=delai, **kwargs)
                # 429 / 5xx : on réessaie après une pause ; 4xx : inutile d'insister
                if rep.status_code == 429 or rep.status_code >= 500:
                    raise ErreurSource(f"HTTP {rep.status_code} sur {url}")
                rep.raise_for_status()
                return rep
            except requests.HTTPError as e:
                raise ErreurSource(f"{e} ({url})") from e
            except (requests.RequestException, ErreurSource) as e:
                derniere_erreur = e
                time.sleep(2 * (essai + 1))
        raise ErreurSource(f"Échec après {self.relances} essais : {derniere_erreur}")

    def get_json(self, url: str, delai: float | None = None):
        rep = self._get(url, timeout=delai)
        try:
            return rep.json()
        except ValueError as e:
            raise ErreurSource(f"Réponse non JSON : {url}") from e

    def telecharger(self, url: str, destination: Path) -> Path:
        """Télécharge un gros fichier sur le disque, par morceaux (mémoire constante)."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        rep = self._get(url, stream=True)
        with open(destination, "wb") as f:
            for morceau in rep.iter_content(chunk_size=1 << 20):
                f.write(morceau)
        return destination


class ClientFichiers:
    """Faux client pour les tests : associe chaque URL à un fichier local."""

    def __init__(self, correspondances: dict[str, Path | None]):
        self.correspondances = correspondances

    def _chemin(self, url: str) -> Path:
        chemin = self.correspondances.get(url)
        if chemin is None:
            raise ErreurSource(f"URL inconnue (simulée injoignable) : {url}")
        return Path(chemin)

    def get_json(self, url: str, delai: float | None = None):
        with open(self._chemin(url), encoding="utf-8") as f:
            return json.load(f)

    def telecharger(self, url: str, destination: Path) -> Path:
        return self._chemin(url)
