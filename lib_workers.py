"""Taches d'arriere-plan de la bibliotheque (QRunnable) : generation des
vignettes, recuperation des metadonnees (par tome et par serie), scan des
dossiers et comptage. Regroupees hors du widget principal, dont elles sont
independantes (elles ne communiquent que par signaux)."""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QImage

import metadata
from archive_handler import Archive, scan_folder
from lib_constants import THUMB_H, THUMB_SCALE, THUMB_W
from storage import Store


class _ThumbSignals(QObject):
    done = Signal(str, QImage)   # chemin du manga, image de couverture
    failed = Signal(str, str)    # chemin, message
    count = Signal(str, int)     # chemin, nombre de pages (estimations de temps)


class ThumbWorker(QRunnable):
    """Extrait la premiere image de l'archive et la reduit, hors du thread UI."""

    def __init__(self, manga_path: str, cache_path: Path):
        super().__init__()
        self.manga_path = manga_path
        self.cache_path = cache_path
        self.signals = _ThumbSignals()

    def run(self):
        try:
            if self.cache_path.exists():
                img = QImage(str(self.cache_path))
                if not img.isNull():
                    self.signals.done.emit(self.manga_path, img)
                    return
            ar = Archive(self.manga_path)
            try:
                data = ar.read_first_page()
                self.signals.count.emit(self.manga_path, len(ar))
            finally:
                ar.close()
            img = QImage.fromData(data)
            if img.isNull():
                raise ValueError("couverture illisible")
            img = img.scaled(THUMB_W * THUMB_SCALE, THUMB_H * THUMB_SCALE,
                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # JPEG q=88 : ~5x plus petit qu'un PNG, encodage/relecture plus
            # rapides, sans difference visible a la taille d'une vignette.
            img.save(str(self.cache_path), "JPEG", 88)
            self.signals.done.emit(self.manga_path, img)
        except Exception as e:
            logging.warning("Vignette impossible pour %s", self.manga_path, exc_info=True)
            self.signals.failed.emit(self.manga_path, str(e))


# ---------------------------------------------------------------- metadonnees (auteur, date)

class _MetaSignals(QObject):
    # chemin, donnees du tome (dict/None), donnees serie fraiches (dict/None), succes
    done = Signal(str, object, object, bool)


class MetaWorker(QRunnable):
    """Cascade ComicInfo.xml -> Google Books -> AniList pour un fichier,
    hors du thread UI (voir metadata.py pour le detail de la strategie)."""

    def __init__(self, path: str, series_name: str, volume, cached_series):
        super().__init__()
        self.path = path
        self.series_name = series_name
        self.volume = volume
        self.cached_series = cached_series
        self.signals = _MetaSignals()

    def run(self):
        data, ok, series_data = metadata.fetch(
            self.path, self.series_name, self.volume, self.cached_series)
        self.signals.done.emit(self.path, data, series_data, ok)


class _SeriesMetaSignals(QObject):
    done = Signal(str, object, bool)   # cle de serie, series_data (dict/None), succes


class SeriesMetaWorker(QRunnable):
    """Recherche AniList au niveau de la serie (une requete pour tous ses
    tomes), pour faire apparaitre l'auteur rapidement au premier scan sans
    attendre les recherches Google Books par tome (throttlees)."""

    def __init__(self, series_key: str, series_name: str):
        super().__init__()
        self.series_key = series_key
        self.series_name = series_name
        self.signals = _SeriesMetaSignals()

    def run(self):
        series_data, ok = metadata.fetch_series(self.series_name)
        self.signals.done.emit(self.series_key, series_data, ok)


class _ScanSignals(QObject):
    done = Signal(list)   # liste des chemins scannes et dedupliques par contenu


class ScanWorker(QRunnable):
    """Scan recursif des dossiers sources + deduplication par empreinte de
    contenu, hors du thread UI : sur un disque reseau ou une grosse
    bibliotheque, ce travail (rglob + lecture de 64 Ko par fichier nouveau)
    prend plusieurs secondes et figerait l'interface s'il tournait sur l'UI.
    Le calcul des empreintes remplit au passage le cache de la Store, si bien
    que la finalisation cote UI (parse des noms, overrides) reste instantanee."""

    def __init__(self, store: Store, folders):
        super().__init__()
        self.store = store
        self.folders = list(folders)
        self.signals = _ScanSignals()

    def run(self):
        seen = set()
        paths = []
        for folder in self.folders:
            try:
                found = scan_folder(folder)
            except Exception:
                logging.warning("Scan impossible du dossier %s", folder, exc_info=True)
                found = []
            for p in found:
                if p not in seen:
                    seen.add(p)
                    paths.append(p)
        # deduplication par contenu (remplit le cache d'empreintes de la Store)
        kept = {}
        result = []
        for p in sorted(paths):
            try:
                key = self.store.key_for(p)
            except Exception:
                key = p
            if key not in kept:
                kept[key] = p
                result.append(p)
        self.signals.done.emit(result)


# ---------------------------------------------------------- gestion des dossiers

class _CountSignals(QObject):
    done = Signal(str, int)      # dossier, nombre de mangas trouves


class _FolderCountWorker(QRunnable):
    """Compte les fichiers CBZ/CBR d'un dossier hors du thread UI, pour
    afficher le nombre de mangas sans figer le panneau a l'ouverture."""

    def __init__(self, folder: str):
        super().__init__()
        self.folder = folder
        self.signals = _CountSignals()

    def run(self):
        try:
            n = len(scan_folder(self.folder))
        except Exception:
            logging.warning("Comptage impossible du dossier %s", self.folder, exc_info=True)
            n = -1
        self.signals.done.emit(self.folder, n)
