"""Controleurs de la bibliotheque : les parties qui possedent des threads et
un etat propre, extraites de LibraryWidget et reliees a lui par signaux.

* ScanController     : scan des dossiers sources, telechargement des tomes
                       cloud, surveillance des dossiers ;
* MetadataController : recuperation des metadonnees (par tome et par serie) ;
* CoverCache         : generation et cache memoire des couvertures.
"""

import logging
import os
import time
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
# metadonnees : nouvel essai d'une recherche en echec (reseau, resultat
# provisoire) pendant la session, apres ces delais successifs (secondes) ;
# au-dela, plus rien avant le prochain lancement
RETRY_DELAYS = (5 * 60, 15 * 60, 60 * 60)
RETRY_CHECK_MS = 60 * 1000


class ScanController(QObject):
    """Scan des dossiers en arriere-plan, telechargement des tomes cloud
    (iCloud Drive / OneDrive) et surveillance des dossiers sources."""

    scanStarted = Signal()
    # chemins locaux (dedupliques), chemins cloud, tous les chemins locaux
    scanned = Signal(list, list, list)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        # pool propre au scan : il ne fait pas la queue derriere les vignettes
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.scanning = False
        self._again = False
        self._worker = None
        self._state = None            # ScanState du dernier scan (incremental, surveillance)
        self._changed_dirs = set()    # dossiers signales depuis le dernier scan
        self._full_soon = False       # un scan complet est attendu

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
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._soon = QTimer(self)
        self._soon.setSingleShot(True)
        self._soon.setInterval(800)
        self._soon.timeout.connect(self._scan_soon)

    def refresh(self):
        """Relance un scan complet (non bloquant). Coalesce les demandes
        rapprochees : un scan deja en cours n'est pas double, il est relance
        a sa fin."""
        self._full_soon = True
        self._start()

    def refresh_soon(self):
        """Scan complet, apres un court delai (plusieurs demandes = un scan)."""
        self._full_soon = True
        self._soon.start()

    def _on_directory_changed(self, path):
        """Dossier modifie (fichier ajoute, retire, renomme) : seul ce dossier
        sera reparcouru, apres un court delai qui regroupe les evenements."""
        self._changed_dirs.add(os.path.normpath(path))
        self._soon.start()

    def _scan_soon(self):
        self._start()

    def _start(self):
        if self.scanning:
            self._again = True
            return
        incremental = not self._full_soon and self._state is not None and self._changed_dirs
        changed = self._changed_dirs if incremental else None
        self._changed_dirs, self._full_soon = set(), False
        self.scanning = True
        self._again = False
        self.scanStarted.emit()
        worker = ScanWorker(self.store, self.store.folders(),
                            previous=self._state if incremental else None, changed=changed)
        worker.signals.done.connect(self._on_done)
        self._worker = worker   # garde une reference (sinon GC)
        self.pool.start(worker)

    def _on_done(self, paths, cloud_paths, local_paths, state=None):
        self.scanning = False
        self._worker = None
        if state is not None:
            self._state = state
        self.scanned.emit(paths, cloud_paths, local_paths)
        self.update_watches()
        self._queue_hydration(cloud_paths)
        if self._again or self._full_soon or self._changed_dirs:
            self._start()

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
        pour les arborescences gigantesques. Les dossiers viennent du dernier
        scan : aucun parcours supplementaire du disque."""
        try:
            dirs = list(dict.fromkeys(self._state.dirs))[:MAX_WATCHED_DIRS] if self._state else []
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
        self._entries = {}            # chemin -> entree, recherches en cours
        self._failed = set()          # echecs : retentes plus tard (voir RETRY_DELAYS)
        self._series_workers = {}
        self._series_pending = set()
        self._series_failed = set()
        self._series_args = {}        # cle -> (nom, indices d'auteur), recherches en cours
        # nouveaux essais programmes : ("volume", chemin) / ("series", cle) ->
        # [nombre d'echecs, echeance (monotonic) ou None, relance]
        self._retries = {}
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(RETRY_CHECK_MS)
        self._retry_timer.timeout.connect(self._run_due_retries)
        self._now = time.monotonic   # remplace dans les tests

    def forget_failures(self, path=None):
        """Autorise une nouvelle tentative immediate (pour un tome, ou pour tout)."""
        if path is None:
            self._failed.clear()
            self._series_failed.clear()
            self._retries.clear()
        else:
            self._failed.discard(path)
            self._retries.pop(("volume", path), None)

    def _schedule_retry(self, key, relaunch):
        """Programme le prochain essai d'une recherche en echec, apres un
        delai croissant (RETRY_DELAYS) ; rien hors ligne (aucune source n'est
        interrogee) ni une fois les delais epuises."""
        failures = (self._retries.get(key) or [0])[0] + 1
        if not self.online() or failures > len(RETRY_DELAYS):
            self._retries[key] = [failures, None, relaunch]
            return
        self._retries[key] = [failures, self._now() + RETRY_DELAYS[failures - 1], relaunch]
        if not self._retry_timer.isActive():
            self._retry_timer.start()

    def _run_due_retries(self):
        now = self._now()
        due = [(key, r) for key, r in self._retries.items() if r[1] is not None and r[1] <= now]
        for (kind, value), retry in due:
            retry[1] = None   # le compte d'echecs est garde pour le delai suivant
            (self._failed if kind == "volume" else self._series_failed).discard(value)
            retry[2]()
        if not any(r[1] is not None for r in self._retries.values()):
            self._retry_timer.stop()

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
            self._entries[path] = entry   # pour un eventuel nouvel essai
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
        entry = self._entries.pop(path, None)
        if not ok or (data or {}).get("partial"):
            self._failed.add(path)
            if entry is not None:
                self._schedule_retry(("volume", path), lambda: self.cached_or_fetch(entry))
        else:
            self._retries.pop(("volume", path), None)
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
        self._series_args[series_key] = (series_name, author_hint)
        worker = SeriesMetaWorker(series_key, series_name, author_hint)
        worker.signals.done.connect(self._on_series_done)
        self._series_workers[series_key] = worker
        self.series_pool.start(worker)

    def _on_series_done(self, series_key, series_data, ok):
        self._series_pending.discard(series_key)
        self._series_workers.pop(series_key, None)
        if ok and series_data is not None:
            self.store.set_series_meta(series_key, series_data)
        name, hint = self._series_args.pop(series_key, (None, None))
        if not ok or series_data is None or series_data.get("partial"):
            self._series_failed.add(series_key)
            if name is not None:
                self._schedule_retry(("series", series_key), lambda: self.ensure_series_author(
                    series_key, name, hint))
        else:
            self._retries.pop(("series", series_key), None)
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
