"""Cache hors ligne du desktop : fichiers d'origine des tomes d'un serveur
Beheread, gardes sur ce PC pour les lire sans connexion.

Quels tomes : la politique de core/offline_cache.py (tomes N-1, N et N+1
de chaque serie en cours, dans un budget de 5 Go reglable), calculee sur la
bibliotheque unifiee. Un tome deja present dans un dossier local n'est
jamais telecharge, et ne compte pas dans le budget.

Quand : au demarrage, a chaque nouvelle liste du serveur, apres une lecture,
et au retour d'une connexion non facturee a l'usage (QNetworkInformation) -
sur une connexion facturee (partage de connexion du telephone), rien n'est
telecharge. Les fichiers qui ne sont plus utiles sont supprimes.

Les fichiers sont nommes par leur empreinte (« <hex>.cbz ») dans le dossier
offline/ des donnees de Beheread ; leur empreinte est verifiee a la fin du
telechargement. Le lecteur les ouvre a la place du serveur (voir
infra/servers.Registry.local_copy)."""

import logging
import re
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from beheread.core import offline_cache
from beheread.infra import servers
from beheread.services.jobs import JobRunner

GB = offline_cache.GB
PLAN_DELAY_MS = 4000          # plusieurs declencheurs rapproches : un seul calcul
RETRY_MS = 5 * 60 * 1000      # telechargement en echec : nouvel essai
_FILE = re.compile(r"^([0-9a-f]{40})(\.[a-z0-9]{1,5})$")


def _hex(path) -> str:
    """Empreinte (hexadecimale) d'un tome de serveur Beheread, ou ""."""
    _server, book_id = servers.split_path(path)
    if book_id and book_id.startswith(servers.FP_BOOK):
        return book_id[len(servers.FP_BOOK):]
    return ""


class _Network:
    """Connexion facturee ou non (QNetworkInformation, si le systeme le dit)."""

    def __init__(self, on_change):
        self.info = None
        try:
            from PySide6.QtNetwork import QNetworkInformation
            feature = QNetworkInformation.Feature.Metered
            if QNetworkInformation.loadBackendByFeatures(feature):
                self.info = QNetworkInformation.instance()
            if self.info is not None:
                self.info.isMeteredChanged.connect(lambda _m: on_change())
                self.info.reachabilityChanged.connect(lambda _r: on_change())
        except Exception:
            logging.info("Etat du reseau indisponible : telechargements sans condition",
                         exc_info=True)
            self.info = None

    def metered(self) -> bool:
        try:
            return bool(self.info is not None and self.info.isMetered())
        except Exception:
            return False


class OfflineFiles(QObject):
    """Fichiers d'origine gardes hors ligne (thread UI ; telechargements
    dans un thread de travail, un a la fois)."""

    changed = Signal()   # fichiers gardes ou espace utilise modifies

    def __init__(self, store, parent=None, folder=None):
        super().__init__(parent)
        self.store = store
        self.folder = Path(folder) if folder is not None else Path(store.dir) / "offline"
        self._lock = threading.Lock()
        self._files = {}           # hex -> (chemin, taille)
        self._wanted = []          # chemins des tomes a garder, par priorite
        self._downloading = None   # chemin en cours
        self._failed = {}          # chemin -> nombre d'echecs
        self._stop = threading.Event()
        self.provider = None       # () -> (infos, livres par cle, masquages) : voir plan()
        self._jobs = JobRunner(QThreadPool(self))
        self._jobs.pool.setMaxThreadCount(1)
        self._timer = QTimer(self, singleShot=True, interval=PLAN_DELAY_MS)
        self._timer.timeout.connect(self.plan)
        self._retry = QTimer(self, singleShot=True, interval=RETRY_MS)
        self._retry.timeout.connect(self._next)
        self.network = _Network(self._on_network)
        self._scan()
        servers.registry.local_copy = self.local_copy

    # ----- etat
    def budget(self) -> int:
        try:
            gb = float(self.store.ui_pref("offline_budget_gb", offline_cache.DESKTOP_BUDGET / GB))
        except (TypeError, ValueError):
            gb = offline_cache.DESKTOP_BUDGET / GB
        return int(max(0.0, gb) * GB)

    def used(self) -> int:
        with self._lock:
            return sum(size for _p, size in self._files.values())

    def local_copy(self, path):
        """Fichier garde pour ce tome du serveur, ou None (thread-safe)."""
        hexa = _hex(path)
        with self._lock:
            found = self._files.get(hexa) if hexa else None
        return str(found[0]) if found else None

    def is_kept(self, path) -> bool:
        return self.local_copy(path) is not None

    def _scan(self):
        files = {}
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            for f in self.folder.iterdir():
                if f.name.endswith(".part"):
                    f.unlink(missing_ok=True)   # telechargement interrompu
                    continue
                m = _FILE.match(f.name)
                if m and f.is_file():
                    files[m.group(1)] = (f, f.stat().st_size)
        except OSError:
            logging.warning("Dossier du cache hors ligne illisible : %s", self.folder,
                            exc_info=True)
        with self._lock:
            self._files = files

    # ----- choix des tomes
    def schedule(self):
        """Recalcul prochain des tomes a garder (declencheurs regroupes)."""
        self._timer.start()

    def plan(self):
        """Tomes a garder d'apres la bibliotheque (voir `provider`) : lance
        les telechargements manquants, supprime ce qui n'est plus utile."""
        self._timer.stop()
        if self.provider is None:
            return
        try:
            infos, books, dismissed = self.provider()
        except Exception:
            logging.warning("Cache hors ligne : bibliotheque illisible", exc_info=True)
            return
        sizes = {key: book.size for key, book in books.items() if book.size}
        keep = offline_cache.volumes_to_keep(infos, sizes, self.budget(), dismissed)
        wanted = [books[key].path for key in keep if key in books]
        self._wanted = wanted
        self._evict({_hex(p) for p in wanted})
        self._next()

    def _evict(self, keep_hex):
        removed = False
        with self._lock:
            gone = [(h, f) for h, (f, _s) in self._files.items() if h not in keep_hex]
        for hexa, f in gone:
            if self._downloading and _hex(self._downloading) == hexa:
                continue
            try:
                f.unlink(missing_ok=True)
            except OSError:
                continue   # ouvert dans le lecteur (Windows) : au prochain calcul
            with self._lock:
                self._files.pop(hexa, None)
            removed = True
        if removed:
            self.changed.emit()

    def _on_network(self):
        if not self.network.metered():
            self._failed.clear()
            self._next()

    def _next(self):
        """Telechargement suivant, s'il en reste un et que la connexion s'y prete."""
        if self._downloading is not None or self.network.metered():
            return
        for path in self._wanted:
            if self.is_kept(path) or self._failed.get(path, 0) >= 3:
                continue
            book = servers.registry.book(path)
            client = servers.registry.client(book.server_id) if book is not None else None
            if client is None or not hasattr(client, "download"):
                continue
            self._download(path, book, client)
            return

    def _download(self, path, book, client):
        hexa = _hex(path)
        dest = self.folder / f"{hexa}{book.ext or '.cbz'}"
        self._downloading = path
        stop = self._stop

        def work():
            self.folder.mkdir(parents=True, exist_ok=True)
            return client.download(book, dest, stop)

        def done(size, err):
            self._downloading = None
            if err is not None:
                self._failed[path] = self._failed.get(path, 0) + 1
                logging.info("Cache hors ligne : « %s » non telecharge (%s)", book.title, err)
                if not self._retry.isActive():
                    self._retry.start()
                return
            with self._lock:
                self._files[hexa] = (dest, size)
            if path not in self._wanted:   # plus utile entre-temps
                self._evict({_hex(p) for p in self._wanted})
            self.changed.emit()
            self._next()
        self._jobs.run(work, done)

    def clear(self):
        """Vide le cache (serveurs retires) ; un telechargement en cours s'arrete."""
        self._wanted = []
        self._evict(set())

    def shutdown(self):
        self._stop.set()
        self._timer.stop()
        self._retry.stop()
        if servers.registry.local_copy == self.local_copy:
            servers.registry.local_copy = None
