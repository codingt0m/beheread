"""Modeles de donnees de la bibliotheque (dataclasses, sans Qt).

Ils remplacent les dictionnaires non types qui circulaient dans toute la
bibliotheque : une faute de frappe sur un champ est desormais une erreur
immediate (et visible par les outils de typage) plutot qu'un `None`
silencieux a l'execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional, Union

Number = Union[int, float]


@dataclass(frozen=True)
class LibraryEntry:
    """Un tome de la bibliotheque, tel que deduit du scan des dossiers."""

    path: str
    title: str                      # nom du fichier sans extension
    series: str                     # nom de serie (deduit ou force a la main)
    volume: Optional[Number] = None  # numero de tome/chapitre, None si absent
    kind: Optional[str] = None      # "volume", "chapter", "cycle", "bare" (voir series.py)
    added: float = 0.0              # date d'ajout a la bibliotheque (epoch)
    detached: bool = False          # sorti a la main de tout regroupement
    manual: bool = False            # place a la main dans une serie

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> Optional["LibraryEntry"]:
        """Entree relue depuis l'instantane persiste, ou None si la donnee
        est inexploitable (fichier ancien ou abime : on l'ignore plutot que
        de planter au demarrage)."""
        if not isinstance(data, dict):
            return None
        path, title = data.get("path"), data.get("title")
        if not isinstance(path, str) or not path or not isinstance(title, str):
            return None
        volume = data.get("volume")
        if not isinstance(volume, (int, float)) or isinstance(volume, bool):
            volume = None
        try:
            added = float(data.get("added") or 0)
        except (TypeError, ValueError):
            added = 0.0
        return cls(path=path, title=title, series=str(data.get("series") or title),
                   volume=volume, kind=data.get("kind") if isinstance(data.get("kind"), str) else None,
                   added=added, detached=bool(data.get("detached")),
                   manual=bool(data.get("manual")))


@dataclass(frozen=True)
class VolumeInfo:
    """Informations de tri et de statut d'un tome (voir library_model.py)."""

    path: str
    key: str                        # empreinte de contenu
    title: str
    series_key: Optional[str] = None  # None si le tome est isole
    volume: Optional[Number] = None
    status: str = "unread"
    last_read: float = 0.0
    added: float = 0.0
    author: str = ""
    year: Optional[int] = None


@dataclass(frozen=True)
class SeriesInfo:
    """Informations agregees d'un dossier de serie (tri, statut)."""

    title: str
    status: str = "unread"
    last_read: float = 0.0
    added: float = 0.0
    author: str = ""
    year: Optional[int] = None
