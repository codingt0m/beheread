"""Serveurs de lecture (Komga, Kavita, OPDS, serveur Beheread) : configuration
active, liste des tomes de chaque serveur et synchronisation de la progression.

Desactive par defaut (preference « servers_enabled ») : sans cette option,
aucun client n'est cree et rien ne part sur le reseau. La synchronisation
(preference « servers_sync ») suit les evenements de lecture comme un
service de suivi (voir tracking.py) : la progression d'un tome distant est
envoyee a son serveur a la fin de chaque seance ; a chaque liste, celle du
serveur est reprise quand elle est plus avancee (lue sur un autre appareil).

Un serveur Beheread a sa propre synchronisation, toujours active
(cross-progression : voir beheread_sync.py). Sa derniere liste est gardee
sur le disque : ses tomes restent dans la bibliotheque sans connexion.
Chaque liste apporte aussi les corrections de bibliotheque de
l'administrateur, recopiees ici (voir infra/shared_library.py).
"""

import json
import logging
import os

from PySide6.QtCore import QThreadPool, Signal

from beheread.i18n import tr
from beheread.infra import servers, shared_library
from beheread.infra.servers import ServerConfig, ServerError, UpdateRequired
from beheread.services.beheread_sync import BeheReadSync
from beheread.services.jobs import JobRunner
from beheread.services.tracking import Tracker


class ServerManager(Tracker):
    NAME = "Serveurs"

    listed = Signal(str, object, str)   # serveur, tomes (ou None), message d'erreur
    changed = Signal()                  # serveurs ou options modifies (preferences)
    syncChanged = Signal(str)           # serveur Beheread : etat de la connexion
    updateRequired = Signal(str)        # serveur Beheread : version plus recente exigee
    progressChanged = Signal(str)       # empreinte lue sur un autre appareil
    journalChanged = Signal()           # journal d'un autre appareil recu

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._jobs = JobRunner(self.pool)
        self._books = {}        # serveur -> tomes de la derniere liste
        self._errors = {}       # serveur -> message de la derniere erreur
        self._fetching = set()
        self._syncs = {}        # serveur Beheread -> BeheReadSync
        self.shared_skip = None  # (section, cle) -> bool : voir _apply_shared
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
        self._reload_beheread(clients)
        self.changed.emit()

    def _reload_beheread(self, clients):
        """Synchronisation des serveurs Beheread."""
        for sync in self._syncs.values():
            sync.stop()
            sync.deleteLater()
        self._syncs = {}
        beheread = {sid: c for sid, c in clients.items() if c.config.kind == "beheread"}
        for sid, client in beheread.items():
            if sid not in self._books:
                books = self._cached_books(client)
                if books:
                    servers.registry.add_books(books)
                    self._books[sid] = books
            sync = BeheReadSync(self.store, client, self)
            sync.stateChanged.connect(lambda sid=sid: self._on_sync_state(sid))
            sync.libraryChanged.connect(lambda sid=sid: self.fetch(sid))
            sync.progressChanged.connect(self.progressChanged)
            sync.journalChanged.connect(self.journalChanged)
            self._syncs[sid] = sync
            sync.start()

    def sync(self, server_id):
        """BeheReadSync d'un serveur Beheread, ou None."""
        return self._syncs.get(server_id)

    def syncs(self) -> dict:
        return dict(self._syncs)

    def _on_sync_state(self, server_id):
        sync = self._syncs.get(server_id)
        if sync is not None and sync.update is not None:
            self.updateRequired.emit(server_id)
        self.syncChanged.emit(server_id)

    # ----- liste gardee (serveur Beheread)
    def _listing_file(self, server_id):
        return os.path.join(str(self.store.dir), "servers", f"{server_id}.json")

    def _cached_books(self, client):
        path = self._listing_file(client.config.id)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return client.parse_books(data.get("library"), data.get("profile"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, AttributeError, ServerError):
            logging.warning("Liste gardee du serveur %s illisible", client.config.id)
            return None

    def _save_listing(self, client):
        if not getattr(client, "last_listing", None):
            return
        library, profile = client.last_listing
        path = self._listing_file(client.config.id)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"library": library, "profile": profile}, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            logging.warning("Liste du serveur %s non gardee", client.config.id, exc_info=True)

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
        self._jobs.run(fn, callback)

    def _on_listed(self, server_id, books, err):
        self._fetching.discard(server_id)
        client = servers.registry.client(server_id)
        if client is None:
            return   # serveur retire ou desactive pendant la requete
        if err is not None:
            message = str(err) if isinstance(err, ServerError) else tr("Réponse inattendue du serveur.")
            if not isinstance(err, ServerError):
                logging.warning("Liste du serveur %s en echec", server_id, exc_info=err)
            self._errors[server_id] = message
            if isinstance(err, UpdateRequired) and server_id in self._syncs:
                self.updateRequired.emit(server_id)
            self.listed.emit(server_id, None, message)
            return
        self._errors.pop(server_id, None)
        servers.registry.add_books(books)
        self._books[server_id] = books
        for book in books:
            self.store.set_page_count(book.path, book.pages)
            self._remember_meta(book)
        if server_id in self._syncs:
            self._save_listing(client)   # la progression : par la synchronisation
            self._apply_shared(server_id, client)
        elif self.sync_enabled():
            self._merge_progress(books)
        self.listed.emit(server_id, books, "")

    def _apply_shared(self, server_id, client):
        """Corrections de bibliotheque du serveur Beheread (series, tomes
        virtuels, metadonnees, couvertures) recopiees ici : le serveur fait
        foi (voir infra/shared_library.py). `shared_skip(section, cle)`,
        pose par Beheread Admin, garde ses corrections pas encore envoyees."""
        library = (getattr(client, "last_listing", None) or (None,))[0]
        shared = library.get("shared") if isinstance(library, dict) else None
        if not isinstance(shared, dict):
            return
        try:
            shared_library.apply(self.store, server_id, shared, self.shared_skip)
        except Exception:
            logging.warning("Donnees de bibliotheque du serveur %s non reprises", server_id,
                            exc_info=True)

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
        celle de Beheread (jamais l'inverse : rien n'est perdu ici)."""
        for book in books:
            if book.progress is None or not book.pages:
                continue
            page, finished = book.progress
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
        for sync in self._syncs.values():
            sync.flush_now()   # fin de seance : sans attendre l'envoi groupe

    def flush_pending(self):
        for sync in self._syncs.values():
            sync.flush()

    def shutdown(self):
        """Fermeture de l'application : flux arretes (la file reste en base)."""
        for sync in self._syncs.values():
            sync.stop()

    def _push(self, path):
        if not servers.is_remote(path) or not self.sync_enabled():
            return
        book = servers.registry.book(path)
        client = servers.registry.client(book.server_id) if book is not None else None
        progress = self.store.get_progress(path)
        if client is None or not client.supports_progress or progress is None:
            return
        if book.server_id in self._syncs:
            return   # serveur Beheread : par sa file d'evenements
        page, _total, finished = progress
        book.progress = (page, bool(finished))

        def report(_result, err, name=book.title):
            if err is not None:
                logging.warning("Progression non envoyee au serveur (%s)", type(err).__name__)
                self.statusChanged.emit(tr("Progression de « {title} » non envoyée au "
                                           "serveur : {error}", title=name, error=err))
        self._run(lambda: client.push_progress(book, page, bool(finished)), report)
