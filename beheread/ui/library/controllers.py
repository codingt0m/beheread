"""Controleurs de la bibliotheque : les parties qui possedent des threads et
un etat propre, extraites de LibraryWidget et reliees a lui par signaux.

* ScanController     : scan des dossiers sources, telechargement des tomes
                       cloud, surveillance des dossiers ;
* MetadataController : recuperation des metadonnees (par tome et par serie) ;
* ChapterMapController : decoupage officiel tomes/chapitres (MangaDex) ;
* CoverCache         : generation et cache memoire des couvertures.
"""

import logging
import os
import time
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import (
    QFileSystemWatcher,
    QObject,
    QThread,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QPixmap

from beheread.core.series import author_hint, normalize_name
from beheread.i18n import tr
from beheread.infra import mangadex, metadata, servers, virtual
from beheread.ui.library.workers import (
    CallWorker,
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
# decoupage officiel tomes/chapitres : redemande apres ce delai (un tome
# qui parait range de nouveaux chapitres), ou apres un echec
CHAPTER_MAP_TTL = 7 * 24 * 3600
CHAPTER_MAP_RETRY = 24 * 3600


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


class ChapterMapController(QObject):
    """Decoupage officiel tomes/chapitres et dernieres parutions (dernier tome,
    dernier chapitre) des series qui ont des chapitres ou dont le nombre de
    tomes parus est inconnu (serie en cours), demandes a MangaDex une serie a
    la fois et gardes en cache (Store.chapter_map)."""

    updated = Signal(str)   # cle de serie dont le decoupage vient d'arriver

    def __init__(self, store, online, parent=None):
        """online() -> bool : la recherche en ligne est-elle autorisee ?"""
        super().__init__(parent)
        self.store = store
        self.online = online
        self._queue = OrderedDict()   # cle -> (nom, indices d'auteur)
        self._call = None             # (cle, CallWorker) en cours
        self._now = time.time         # remplace dans les tests

    def ensure(self, key, name, hints=None, incomplete=False):
        """Demande le decoupage de la serie s'il manque ou date. `incomplete` :
        le decoupage en cache ne connait pas le dernier tome possede - il est
        redemande des CHAPTER_MAP_RETRY (un jour) au lieu d'une semaine."""
        if not self.online() or key in self._queue or (self._call and self._call[0] == key):
            return
        cached = self.store.chapter_map(key)
        if cached and cached.get("v") == mangadex.RANGES_VERSION:
            age = self._now() - float(cached.get("at") or 0)
            stale = CHAPTER_MAP_RETRY if cached.get("failed") or incomplete else CHAPTER_MAP_TTL
            if age < stale:
                return
        self._queue[key] = (name, hints)
        self._next()

    def _next(self):
        if self._call is not None or not self._queue:
            return
        key, (name, hints) = self._queue.popitem(last=False)
        known = (self.store.chapter_map(key) or {}).get("id")
        if not known:
            sm = self.store.series_meta(key) or {}
            known = sm.get("mangadex_id")

        def fetch():
            if known:
                return known, mangadex.aggregate(known)
            return mangadex.series_aggregate(name, hints)
        call = CallWorker(fetch)
        call.signals.done.connect(lambda result, err: self._on_done(key, result, err))
        self._call = (key, call)
        QThreadPool.globalInstance().start(call)

    def _on_done(self, key, result, err):
        self._call = None
        if err is not None:
            logging.info("Decoupage MangaDex indisponible pour %s : %s", key, err)
            self.store.set_chapter_map(key, {"at": self._now(), "failed": True,
                                             "v": mangadex.RANGES_VERSION})
        else:
            manga_id, data = result if result else (None, {})
            self.store.set_chapter_map(key, {
                "at": self._now(), "id": manga_id, "ranges": data.get("ranges") or {},
                "last_volume": data.get("last_volume"), "last_chapter": data.get("last_chapter"),
                "v": mangadex.RANGES_VERSION})
            if data.get("ranges") or data.get("last_volume") or data.get("last_chapter"):
                self.updated.emit(key)
        self._next()


class MetadataController(QObject):
    """Metadonnees auteur/date : cascade par tome (metadonnees du fichier,
    ISBN, serie, Google Books : voir infra/metadata.py), et recherche au
    niveau serie pour que l'auteur apparaisse vite pour tous les tomes. Un pool par hote distant,
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
        self._prioritized = set()     # recherches deja passees devant (voir prioritize)
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

    def failure(self, path):
        """Etat d'une recherche en echec pour ce tome (reseau, resultat
        provisoire), ou None : {"due": secondes avant le prochain essai
        automatique, ou None s'il n'y en aura plus dans la session}."""
        if path not in self._failed or not self.online():
            return None
        retry = self._retries.get(("volume", path))
        due = None if not retry or retry[1] is None else max(0.0, retry[1] - self._now())
        return {"due": due}

    def retry_now(self, entry):
        """« Reessayer maintenant » : relance tout de suite la recherche de ce
        tome et celle de sa serie, sans attendre l'essai programme."""
        self.forget_failures(entry.path)
        key = normalize_name(entry.series)
        self._series_failed.discard(key)
        self._retries.pop(("series", key), None)
        self.cached_or_fetch(entry)

    def prioritize(self, path):
        """Tome a l'ecran : sa recherche, si elle attend encore dans la file,
        passe devant celles des tomes hors de vue."""
        worker = self._workers.get(path)
        # une tache demarree peut deja avoir ete detruite par Qt (elle l'est a
        # la fin de run, avant que sa reponse ne soit traitee ici) : on ne
        # touche qu'a une tache encore en file
        if worker is None or worker.started or path in self._prioritized:
            return
        self._prioritized.add(path)
        try:
            taken = self.pool.tryTake(worker)
        except RuntimeError:   # demarree et terminee entre-temps
            return
        if taken:
            self.pool.start(worker, 1)

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
        if servers.is_remote(path) or virtual.is_virtual(path):
            # tome d'un serveur de lecture : auteur et annee donnes par le
            # serveur (voir ServerManager) ; tome virtuel : ceux de sa serie.
            # Rien n'est cherche en ligne.
            cached = self.store.volume_meta(path)
            return None if not cached or cached.get("not_found") else cached
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
        self._prioritized.discard(path)
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


# memoire des couvertures decodees (a la taille d'affichage) : budget en
# octets, et nombre minimal garde quoi qu'il arrive (voir CoverCache.capacity)
COVER_BUDGET_BYTES = 256 * 1024 * 1024
COVER_MIN_KEPT = 150


class CoverCache(QObject):
    """Couvertures des tomes : generees en arriere-plan (ThumbWorker, cache
    disque), gardees en memoire a la taille d'affichage maximale.

    Elles sont demandees au moment ou une case est peinte (lookup, appele par
    les delegates) ou va l'etre (request, cases proches de la zone visible) :
    une bibliotheque de 5 000 tomes ne met plus 5 000 taches en file au scan.
    La memoire est bornee (cache LRU, voir capacity) : une couverture sortie
    du cache est relue depuis le cache disque si sa case revient a l'ecran."""

    coverReady = Signal(str)   # chemin du tome dont la couverture vient d'arriver

    def __init__(self, store, display_size, parent=None):
        super().__init__(parent)
        self.store = store
        self.display_size = display_size
        # pool propre : les couvertures ne retardent ni le lecteur ni le scan
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(2, QThread.idealThreadCount() // 2))
        self.cache = OrderedDict()   # chemin -> QPixmap, du moins au plus recent
        self._pending = set()
        self._workers = {}
        self._failed = {}            # illisibles -> message : pas de nouvel essai a chaque peinture
        self._seq = 0                # la derniere demandee passe en premier
        self.min_kept = 0            # cases visibles (voir LibraryWidget)

    @property
    def capacity(self) -> int:
        """Nombre de couvertures gardees : budget memoire, mais jamais moins
        que deux fois ce qui est a l'ecran (sinon une couverture visible
        serait evincee par une autre, puis regeneree, sans fin)."""
        per_cover = max(1, self.display_size.width() * self.display_size.height() * 4)
        return max(COVER_MIN_KEPT, COVER_BUDGET_BYTES // per_cover, 2 * self.min_kept)

    def get(self, path):
        pm = self.cache.get(path)
        if pm is not None:
            self.cache.move_to_end(path)
        return pm

    def lookup(self, path):
        """Couverture a peindre (delegate), ou None : elle est alors demandee
        en arriere-plan, et coverReady la signalera."""
        pm = self.get(path)
        if pm is None and path:
            self.request(path)
        return pm

    def request(self, path):
        """Genere la couverture si elle n'est ni en memoire, ni en cours, ni
        illisible."""
        if path in self.cache or path in self._pending or path in self._failed:
            return
        self._request(path)

    def error(self, path):
        """Message d'erreur de la couverture de ce tome si elle n'a pas pu
        etre lue (archive abimee, outil RAR absent...), sinon None."""
        return self._failed.get(path)

    def retry(self, path):
        """Nouvel essai (« Reessayer » de la fenetre d'erreur)."""
        self._failed.pop(path, None)
        self.request(path)

    def rename(self, old_path, new_path):
        if old_path in self.cache:
            self.cache[new_path] = self.cache.pop(old_path)

    def forget(self, paths):
        for p in paths:
            self.cache.pop(p, None)
            self._failed.pop(p, None)

    def clear(self):
        self.cache.clear()
        self._failed.clear()

    def _request(self, path):
        self._pending.add(path)
        worker = ThumbWorker(path, self.store.thumb_path(path), self.display_size,
                             self.store.custom_cover(path))
        worker.signals.done.connect(self._on_done)
        worker.signals.failed.connect(self._on_failed)
        worker.signals.count.connect(self.store.set_page_count)
        self._workers[path] = worker
        self._seq += 1
        self.pool.start(worker, self._seq)

    def _on_done(self, path, image):
        self._pending.discard(path)
        self._workers.pop(path, None)
        self.cache[path] = QPixmap.fromImage(image)
        self.cache.move_to_end(path)
        while len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
        self.coverReady.emit(path)

    def _on_failed(self, path, message):
        # vignette « illisible » ; le detail est dans le menu contextuel
        self._pending.discard(path)
        self._workers.pop(path, None)
        self._failed[path] = message or tr("Erreur inconnue")
        self.coverReady.emit(path)   # la case se redessine en « illisible »
