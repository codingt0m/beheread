"""Source de la bibliotheque : les dossiers de cet ordinateur, ou un serveur
de lecture (Komga, Kavita, OPDS : voir infra/servers.py et
services/servers.py), choisie dans l'en-tete.

Mixin de LibraryWidget. Pendant la consultation d'un serveur, la grille
montre ses tomes (memes series, tris, filtres et recherche) ; le scan des
dossiers locaux continue en arriere-plan et ses resultats sont appliques au
retour sur « Sur cet ordinateur »."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from beheread.core import units
from beheread.core.models import LibraryEntry
from beheread.core.series import normalize_name
from beheread.i18n import tr
from beheread.infra import servers as remote
from beheread.infra.storage import Store

LOCAL = "local"


class SourcesMixin:
    def _init_sources(self):
        self.servers = None             # ServerManager, fourni par app.py (set_servers)
        self._source = LOCAL
        self._local_entries = None      # entrees locales mises de cote pendant un serveur
        self._local_results = None      # scan local termine pendant un serveur

    # ----- en-tete -----
    def _build_source_switch(self):
        self.source_switch = QWidget()
        self.source_switch.setObjectName("sourceSwitch")
        self.source_switch.setAccessibleName(tr("Source de la bibliothèque"))
        layout = QHBoxLayout(self.source_switch)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._source_group = QButtonGroup(self.source_switch)
        self._source_group.setExclusive(True)
        self._source_buttons = {}
        self.source_switch.hide()
        return self.source_switch

    def source_switch_css(self, c, accent) -> str:
        return f"""
            #sourceSwitch {{ background: {c['list_bg']}; border: 1px solid {c['border']};
                             border-radius: 15px; }}
            QPushButton#sourceBtn {{ color: {c['text_dim']}; background: transparent; border: none;
                                    border-radius: 12px; padding: 3px 12px; }}
            QPushButton#sourceBtn:hover {{ color: {c['text']}; }}
            QPushButton#sourceBtn:checked {{ color: {c['text']}; background: {c['button']};
                                            font-weight: 600; }}
            QPushButton#sourceBtn:focus {{ border: 1px solid {accent}; }}
        """

    def _source_choices(self):
        choices = [(LOCAL, tr("Sur cet ordinateur"))]
        if self.servers is not None and self.servers.enabled():
            choices += [(c.id, c.name) for c in self.servers.configs()]
        return choices

    def _refresh_sources(self):
        """Boutons de l'en-tete d'apres les serveurs configures (masques s'il
        n'y en a aucun ou si l'option est desactivee)."""
        layout = self.source_switch.layout()
        for btn in self._source_buttons.values():
            self._source_group.removeButton(btn)
            layout.removeWidget(btn)
            btn.deleteLater()
        self._source_buttons = {}
        choices = self._source_choices()
        for key, label in choices:
            btn = QPushButton(label)
            btn.setObjectName("sourceBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.TabFocus)
            btn.clicked.connect(lambda _c=False, k=key: self.select_source(k))
            self._source_group.addButton(btn)
            layout.addWidget(btn)
            self._source_buttons[key] = btn
        self.source_switch.setVisible(len(choices) > 1)
        if self._source not in self._source_buttons:
            self.select_source(LOCAL)
        self._source_buttons[self._source].setChecked(True)
        self._update_source_status()
        self._balance_header()

    def _update_source_status(self):
        """Infobulle de chaque serveur : nombre de tomes ou erreur."""
        if self.servers is None:
            return
        for key, btn in self._source_buttons.items():
            if key == LOCAL:
                continue
            books, error = self.servers.books(key), self.servers.error(key)
            if error:
                btn.setToolTip(tr("Hors ligne : {error}", error=error))
            elif books is not None:
                btn.setToolTip(tr("Connecté · {n} tomes", n=len(books)))
            else:
                btn.setToolTip("")

    # ----- services -----
    def set_servers(self, manager):
        self.servers = manager
        manager.listed.connect(self._on_server_listed)
        manager.changed.connect(self._refresh_sources)
        self._refresh_sources()
        wanted = self.store.ui_pref("library_source", LOCAL)
        if wanted in self._source_buttons:
            self.select_source(wanted)

    def is_remote_source(self) -> bool:
        return self._source != LOCAL

    @staticmethod
    def _is_remote(path) -> bool:
        return remote.is_remote(path)

    def select_source(self, source):
        if source not in self._source_buttons and source != LOCAL:
            source = LOCAL
        if source == self._source:
            if source != LOCAL and self.servers is not None and self.servers.books(source) is None:
                self.servers.fetch(source)
            return
        if self._current_series is not None:
            self._current_series = None
            self.btn_back.hide()
        self.search_edit.clear()
        if self._source == LOCAL:
            self._local_entries = list(self._file_entries)
        self._source = source
        self.store.set_ui_pref("library_source", source)
        btn = self._source_buttons.get(source)
        if btn is not None:
            btn.setChecked(True)
        if source == LOCAL:
            results, self._local_results = self._local_results, None
            if results is not None:
                self._apply_scan_results(*results)
            else:
                self._set_entries(self._local_entries or [])
                self._rebuild_list(keep_position=False)
            self._local_entries = None
            self.scanner.refresh()
            return
        books = self.servers.books(source) if self.servers is not None else None
        if books is not None:
            self._apply_remote_books(books, keep_position=False)
        else:
            self._set_entries([])
            self._rebuild_list(keep_position=False)
        if self.servers is not None:
            self.servers.fetch(source)

    def _refresh_source(self):
        """Rafraichir (F5) sur un serveur : nouvelle liste de ses tomes, et
        regroupements modifies appliques tout de suite."""
        books = self.servers.books(self._source) if self.servers is not None else None
        if books is not None:
            self._apply_remote_books(books)
        if self.servers is not None:
            self.servers.fetch(self._source)

    def _on_server_listed(self, server_id, books, _error):
        self._update_source_status()
        if server_id != self._source:
            return
        if books is not None:
            self._apply_remote_books(books)
        elif not self._entries:
            self._update_empty_state(False, self._search_hits is not None)

    def _apply_remote_books(self, books, keep_position=True):
        added = self.store.ensure_added([b.path for b in books])
        entries = []
        for b in books:
            series, detached = b.series, False
            override = self.store.series_override(b.path)
            if override == Store.SERIES_DETACHED:
                detached = True
            elif override:
                series = override
            entries.append(LibraryEntry(
                path=b.path, title=b.title, series=series, volume=b.number,
                kind="volume" if b.number is not None else None, added=added.get(b.path, 0),
                detached=detached, manual=bool(override) and not detached))
        if entries != self._file_entries:
            self._set_entries(entries)
            self._rebuild_list(keep_position=keep_position)
        elif not entries:
            self._update_empty_state(False, self._search_hits is not None)

    def _remote_empty_state(self):
        """Etat vide pendant la consultation d'un serveur."""
        config = self.servers.config(self._source) if self.servers is not None else None
        name = config.name if config is not None else ""
        error = self.servers.error(self._source) if self.servers is not None else ""
        if error:
            self._set_empty_state(tr("Serveur injoignable"), error, tr("Réessayer"),
                                  lambda: self.servers.fetch(self._source))
        elif self.servers is not None and self.servers.fetching(self._source):
            self._set_empty_state(tr("Chargement de « {name} »…", name=name),
                                  tr("Les tomes du serveur apparaîtront dans un instant."))
        else:
            self._set_empty_state(tr("Aucun tome sur ce serveur"), "", tr("Réessayer"),
                                  lambda: self.servers.fetch(self._source))

    # ----- lecteur -----
    def next_volume(self, path):
        """Element suivant dans sa serie (voir units.next_in_series : le tome
        suivant, apres le dernier tome le premier chapitre), ou None. Vaut
        pour les tomes locaux comme distants de la bibliotheque, chapitres
        ranges dans un autre dossier compris ; un fichier ouvert hors
        bibliotheque est cherche par le lecteur dans son dossier
        (archive.find_next_volume)."""
        e = self._entry_by_path.get(path)
        if e is None or e.volume is None or e.detached:
            return None
        grp = self._group_entries(self._entries).get(normalize_name(e.series)) or [e]
        return units.next_in_series(path, [(o.path, self._unit(o), o.volume) for o in grp])
