"""Controleurs de la bibliotheque : les parties qui possedent des threads et
un etat propre, extraites de LibraryWidget et reliees a lui par signaux.

* ScanController     : scan des dossiers sources, telechargement des tomes
                       cloud, surveillance des dossiers ;
* MetadataController : recuperation des metadonnees (par tome et par serie) ;
* CoverCache         : generation et cache memoire des couvertures.
"""

import logging
import os
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QThreadPool, QTimer, Signal
from PySide6.QtGui import QPixmap

from beheread.core.series import author_hint, normalize_name
from beheread.infra import metadata
from beheread.ui.library.constants import (
    ROLE_IS_SERIES,
    ROLE_PIXMAP,
    ROLE_PIXMAP2,
    ROLE_PIXMAP3,
    ROLE_SERIES_PATHS,
)
from beheread.ui.library.workers import (
    HydrateWorker,
    MetaWorker,
    ScanWorker,
    SeriesMetaWorker,
    ThumbWorker,
)

MAX_WATCHED_DIRS = 2000


class ScanController(QObject):
    """Scan des dossiers en arriere-plan, telechargement des tomes cloud
    (iCloud Drive / OneDrive) et surveillance des dossiers sources."""

    scanStarted = Signal()
    # chemins locaux (dedupliques), chemins cloud, tous les chemins locaux
    scanned = Signal(list, list, list)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.pool = QThreadPool.globalInstance()
        self.scanning = False
        self._again = False
        self._worker = None

        # telechargement des tomes cloud non presents en local : pool dedie et
        # limite pour ne pas saturer le reseau ni monopoliser les threads des
        # vignettes. Les tomes concernes apparaissent au rescan declenche a la
        # fin de chaque telechargement.
        self.hydrate_pool = QThreadPool(self)
        self.hydrate_pool.setMaxThreadCount(2)
        self._hydrate_workers = {}
        self._hydrate_pending = set()
        self._hydrate_failed = set()   # echecs : pas retente avant redemarrage

        # surveillance : un fichier ajoute ou retire declenche un rescan
        # (debounce : plusieurs evenements rapproches = un seul scan)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _p: self.refresh_soon())
        self._soon = QTimer(self)
        self._soon.setSingleShot(True)
        self._soon.setInterval(800)
        self._soon.timeout.connect(self.refresh)

    def refresh(self):
        """Relance un scan (non bloquant). Coalesce les demandes rapprochees :
        un scan deja en cours n'est pas double, il est relance a sa fin."""
        if self.scanning:
            self._again = True
            return
        self.scanning = True
        self._again = False
        self.scanStarted.emit()
        worker = ScanWorker(self.store, self.store.folders())
        worker.signals.done.connect(self._on_done)
        self._worker = worker   # garde une reference (sinon GC)
        self.pool.start(worker)

    def refresh_soon(self):
        self._soon.start()

    def _on_done(self, paths, cloud_paths, local_paths):
        self.scanning = False
        self._worker = None
        self.scanned.emit(paths, cloud_paths, local_paths)
        self.update_watches()
        self._queue_hydration(cloud_paths)
        if self._again:
            self.refresh()

    # ----- tomes cloud -----
    def _queue_hydration(self, cloud_paths):
        for p in cloud_paths:
            if p in self._hydrate_pending or p in self._hydrate_failed:
                continue
            self._hydrate_pending.add(p)
            worker = HydrateWorker(p)
            worker.signals.done.connect(self._on_hydrated)
            self._hydrate_workers[p] = worker
            self.hydrate_pool.start(worker)

    def _on_hydrated(self, path, ok):
        self._hydrate_pending.discard(path)
        self._hydrate_workers.pop(path, None)
        if ok:
            self.refresh_soon()   # le fichier est en local : il apparaitra au rescan
        else:
            self._hydrate_failed.add(path)

    # ----- surveillance -----
    def update_watches(self):
        """(Re)installe la surveillance sur chaque dossier source et ses
        sous-dossiers (QFileSystemWatcher n'est pas recursif), avec un plafond
        pour les arborescences gigantesques."""
        try:
            dirs, seen = [], set()
            for folder in self.store.folders():
                if not os.path.isdir(folder):
                    continue
                for root, _subdirs, _files in os.walk(folder):
                    if root not in seen:
                        seen.add(root)
                        dirs.append(root)
                    if len(dirs) >= MAX_WATCHED_DIRS:
                        break
                if len(dirs) >= MAX_WATCHED_DIRS:
                    break
            current = self._watcher.directories()
            if set(dirs) == set(current):
                return   # deja a jour (appele apres CHAQUE scan)
            if current:
                self._watcher.removePaths(current)
            if dirs:
                self._watcher.addPaths(dirs)
        except Exception:
            # non bloquant : le bouton « Rafraichir » reste un filet de secours
            logging.warning("Echec de la surveillance des dossiers sources", exc_info=True)


class MetadataController(QObject):
    """Metadonnees auteur/date : cascade ComicInfo.xml -> Google Books ->
    AniList -> MangaDex -> BnF par tome, et recherche au niveau serie pour que
    l'auteur apparaisse vite pour tous les tomes. Un pool par hote distant,
    limite a 1 thread, pour rester poli avec les API."""

    volumeUpdated = Signal(str)     # chemin du tome dont les metadonnees ont change
    seriesUpdated = Signal(str)     # cle de serie

    def __init__(self, store, online, parent=None):
        """online() -> bool : la recherche en ligne est-elle autorisee ?"""
        super().__init__(parent)
        self.store = store
        self.online = online
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.series_pool = QThreadPool(self)
        self.series_pool.setMaxThreadCount(1)
        self._workers = {}
        self._pending = set()
        self._failed = set()          # echecs : pas retente avant redemarrage
        self._series_workers = {}
        self._series_pending = set()
        self._series_failed = set()

    def forget_failures(self, path=None):
        """Autorise une nouvelle tentative (pour un tome, ou pour tout)."""
        if path is None:
            self._failed.clear()
            self._series_failed.clear()
        else:
            self._failed.discard(path)

    def cached_or_fetch(self, entry):
        """Metadonnees en cache de ce tome (ou None si pas encore connues) ;
        declenche une recherche en arriere-plan si necessaire. Un cache ecrit
        par une cascade plus ancienne (voir metadata.is_stale) est retente ;
        un resultat perime reste affiche en attendant le nouveau."""
        path = entry.path
        cached = self.store.volume_meta(path)
        if cached is not None and not metadata.is_stale(cached):
            return None if cached.get("not_found") else cached
        series_key = normalize_name(entry.series)
        hint = author_hint(Path(path).stem)
        self.ensure_series_author(series_key, entry.series, hint)
        if path not in self._pending and path not in self._failed:
            self._pending.add(path)
            cached_series = self.store.series_meta(series_key)
            if cached_series is not None and metadata.is_stale(cached_series):
                cached_series = None
            worker = MetaWorker(path, entry.series, entry.volume, cached_series,
                                online=self.online(), author_hint=hint)
            worker.signals.done.connect(
                lambda p, d, s, ok, key=series_key: self._on_volume_done(p, d, s, ok, key))
            self._workers[path] = worker
            self.pool.start(worker)
        return None if not cached or cached.get("not_found") else cached

    def _on_volume_done(self, path, data, series_data, ok, series_key):
        self._pending.discard(path)
        self._workers.pop(path, None)
        if series_data is not None:
            self.store.set_series_meta(series_key, series_data)
        if ok:
            self.store.set_volume_meta(path, data if data else metadata.not_found_sentinel())
        if not ok or (data or {}).get("partial"):
            self._failed.add(path)   # retente a la prochaine session
        self.volumeUpdated.emit(path)

    def ensure_series_author(self, series_key, series_name, author_hint=None):
        """Recherche au niveau serie (une fois), seulement si la recherche en
        ligne est autorisee et que rien d'a jour n'est en cache."""
        if not self.online():
            return
        cached = self.store.series_meta(series_key)
        if cached is not None and not metadata.is_stale(cached):
            return
        if series_key in self._series_pending or series_key in self._series_failed:
            return
        self._series_pending.add(series_key)
        worker = SeriesMetaWorker(series_key, series_name, author_hint)
        worker.signals.done.connect(self._on_series_done)
        self._series_workers[series_key] = worker
        self.series_pool.start(worker)

    def _on_series_done(self, series_key, series_data, ok):
        self._series_pending.discard(series_key)
        self._series_workers.pop(series_key, None)
        if ok and series_data is not None:
            self.store.set_series_meta(series_key, series_data)
        if not ok or series_data is None or series_data.get("partial"):
            self._series_failed.add(series_key)   # retente a la prochaine session
        self.seriesUpdated.emit(series_key)


class CoverCache(QObject):
    """Couvertures des tomes : generees en arriere-plan (ThumbWorker, cache
    disque), gardees en memoire a la taille d'affichage maximale, et
    distribuees aux items abonnes (un tome, ou un dossier de serie qui
    empile jusqu'a trois couvertures)."""

    coverReady = Signal(str)   # chemin du tome dont la couverture vient d'arriver

    def __init__(self, store, display_size, parent=None):
        super().__init__(parent)
        self.store = store
        self.display_size = display_size
        self.pool = QThreadPool.globalInstance()
        self.cache = {}            # chemin -> QPixmap
        self._pending = set()
        self._workers = {}
        self._subscribers = {}     # chemin -> items qui affichent cette couverture

    def reset_subscribers(self):
        """A appeler quand la liste est reconstruite (anciens items detruits)."""
        self._subscribers = {}

    def get(self, path):
        return self.cache.get(path)

    def bind(self, item, path, role):
        """Associe la couverture de `path` a `item` (au role donne) : tout de
        suite si elle est en cache, sinon a son arrivee."""
        pm = self.cache.get(path)
        if pm is not None:
            item.setData(role, pm)
            return
        self._subscribers.setdefault(path, []).append(item)
        self._request(path)

    def rename(self, old_path, new_path):
        if old_path in self.cache:
            self.cache[new_path] = self.cache.pop(old_path)

    def forget(self, paths):
        for p in paths:
            self.cache.pop(p, None)

    def clear(self):
        self.cache.clear()

    def _request(self, path):
        if path in self._pending:
            return
        self._pending.add(path)
        worker = ThumbWorker(path, self.store.thumb_path(path), self.display_size)
        worker.signals.done.connect(self._on_done)
        worker.signals.failed.connect(self._on_failed)
        worker.signals.count.connect(self.store.set_page_count)
        self._workers[path] = worker
        self.pool.start(worker)

    def _on_done(self, path, image):
        pm = QPixmap.fromImage(image)
        self.cache[path] = pm
        self._pending.discard(path)
        self._workers.pop(path, None)
        for item in self._subscribers.get(path, ()):
            if item.data(ROLE_IS_SERIES):
                cover_paths = item.data(ROLE_SERIES_PATHS) or []
                for role, p in zip((ROLE_PIXMAP, ROLE_PIXMAP2, ROLE_PIXMAP3), cover_paths):
                    if p == path:
                        item.setData(role, pm)
            else:
                item.setData(ROLE_PIXMAP, pm)
        self.coverReady.emit(path)

    def _on_failed(self, path, _message):
        # la vignette reste grise ; l'erreur detaillee apparaitra a l'ouverture
        self._pending.discard(path)
        self._workers.pop(path, None)
