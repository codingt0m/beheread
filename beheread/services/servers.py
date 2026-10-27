"""Serveurs de lecture (Komga, Kavita, OPDS) : configuration active, liste
des tomes de chaque serveur et synchronisation de la progression.

Desactive par defaut (preference « servers_enabled ») : sans cette option,
aucun client n'est cree et rien ne part sur le reseau. La synchronisation
(preference « servers_sync ») suit les evenements de lecture comme un
service de suivi (voir tracking.py) : la progression d'un tome distant est
envoyee a son serveur a la fin de chaque seance ; a chaque liste, celle du
serveur est reprise quand elle est plus avancee (lue sur un autre appareil).
"""

import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from beheread.i18n import tr
from beheread.infra import servers
from beheread.infra.servers import ServerConfig, ServerError
from beheread.services.tracking import Tracker


class _Signals(QObject):
    done = Signal(object, object)   # resultat, exception (ou None)


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn()
        except Exception as e:   # erreur reseau ou reponse inattendue : rapportee
            self.signals.done.emit(None, e)
            return
        self.signals.done.emit(result, None)


class ServerManager(Tracker):
    NAME = "Serveurs"

    listed = Signal(str, object, str)   # serveur, tomes (ou None), message d'erreur
    changed = Signal()                  # serveurs ou options modifies (preferences)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._books = {}        # serveur -> tomes de la derniere liste
        self._errors = {}       # serveur -> message de la derniere erreur
        self._fetching = set()
        self._jobs = set()      # references des taches en cours (sinon GC)
        self.reload()

    # ----- configuration
    def enabled(self) -> bool:
        return bool(self.store.ui_pref("servers_enabled", False))

    def sync_enabled(self) -> bool:
        return self.enabled() and bool(self.store.ui_pref("servers_sync", True))

    def connected(self) -> bool:
        return self.enabled() and bool(self.configs())

    def configs(self) -> list:
        found = (ServerConfig.from_dict(s) for s in self.store.servers())
        return [c for c in found if c is not None]

    def config(self, server_id):
        return next((c for c in self.configs() if c.id == server_id), None)

    def reload(self):
        """Recree les clients d'apres les preferences (apres une modification)."""
        clients = {}
        if self.enabled():
            for config in self.configs():
                try:
                    clients[config.id] = servers.make_client(
                        config, self.store.server_secret(config.id) or "")
                except ServerError:
                    logging.warning("Serveur %s : adresse inutilisable", config.id)
        servers.registry.set_clients(clients)
        for gone in set(self._books) - set(clients):
            self._books.pop(gone, None)
            self._errors.pop(gone, None)
        self.changed.emit()

    # ----- liste des tomes
    def books(self, server_id):
        """Tomes de la derniere liste de ce serveur, ou None."""
        return self._books.get(server_id)

    def error(self, server_id) -> str:
        return self._errors.get(server_id, "")

    def fetching(self, server_id) -> bool:
        return server_id in self._fetching

    def fetch(self, server_id):
        """Demande la liste des tomes du serveur (en arriere-plan) : resultat
        par le signal `listed`."""
        client = servers.registry.client(server_id)
        if client is None or server_id in self._fetching:
            return
        self._fetching.add(server_id)
        self._run(client.books, lambda books, err: self._on_listed(server_id, books, err))

    def _run(self, fn, callback):
        job = _Job(fn)
        self._jobs.add(job)

        def done(result, err, job=job):
            self._jobs.discard(job)
            callback(result, err)
        job.signals.done.connect(done)
        self.pool.start(job)

    def _on_listed(self, server_id, books, err):
        self._fetching.discard(server_id)
        if servers.registry.client(server_id) is None:
            return   # serveur retire ou desactive pendant la requete
        if err is not None:
            message = str(err) if isinstance(err, ServerError) else tr("Réponse inattendue du serveur.")
            if not isinstance(err, ServerError):
                logging.warning("Liste du serveur %s en echec", server_id, exc_info=err)
            self._errors[server_id] = message
            self.listed.emit(server_id, None, message)
            return
        self._errors.pop(server_id, None)
        servers.registry.add_books(books)
        self._books[server_id] = books
        for book in books:
            self.store.set_page_count(book.path, book.pages)
            self._remember_meta(book)
        if self.sync_enabled():
            self._merge_progress(books)
        self.listed.emit(server_id, books, "")

    def _remember_meta(self, book):
        """Auteur et annee donnes par le serveur, ranges comme les
        metadonnees trouvees en ligne (une saisie a la main reste prioritaire)."""
        if not (book.author or book.year):
            return
        current = self.store.volume_meta(book.path) or {}
        if current.get("source") == "manual":
            return
        data = {"source": "server", "authors": [a for a in book.author.split(", ") if a],
                "published_year": book.year}
        if current != data:
            self.store.set_volume_meta(book.path, data)

    def _merge_progress(self, books):
        """Reprend la progression du serveur quand elle est plus avancee que
        celle de Beheread (jamais l'inverse : rien n'est perdu ici). Serveur
        Beheread : la plus recente l'emporte, qu'elle avance ou recule (meme
        regle que la synchro, core/profile_sync.py)."""
        for book in books:
            if book.progress is None:
                continue
            page, finished = book.progress
            if book.progress_ts:
                if book.progress_ts > self.store.progress_ts(book.path):
                    total = book.pages or max(page + 1, 1)
                    self.store.set_progress(book.path, page, total, finished)
                continue
            if not book.pages:
                continue
            local = self.store.get_progress(book.path)
            if local is not None and local[2]:
                continue
            if finished:
                self.store.set_progress(book.path, book.pages - 1, book.pages, True)
            elif page > 0 and (local is None or page > local[0]):
                self.store.set_progress(book.path, page, book.pages, False)

    # ----- synchronisation (service de suivi)
    def on_volumes_finished(self, paths):
        for path in paths:
            self._push(path)

    def on_session_end(self, path):
        self._push(path)

    def flush_pending(self):
        pass   # rien n'est mis en attente : la prochaine seance renverra l'etat

    def _push(self, path):
        if not servers.is_remote(path) or not self.sync_enabled():
            return
        book = servers.registry.book(path)
        client = servers.registry.client(book.server_id) if book is not None else None
        progress = self.store.get_progress(path)
        if client is None or not client.supports_progress or progress is None:
            return
        page, _total, finished = progress
        book.progress = (page, bool(finished))

        def report(_result, err, name=book.title):
            if err is not None:
                logging.warning("Progression non envoyee au serveur (%s)", type(err).__name__)
                self.statusChanged.emit(tr("Progression de « {title} » non envoyée au "
                                           "serveur : {error}", title=name, error=err))
        self._run(lambda: client.push_progress(book, page, bool(finished)), report)
