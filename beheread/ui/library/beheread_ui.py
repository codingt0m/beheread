"""Serveur Beheread dans la bibliotheque (maquette « Bibliotheque unifiee du
desktop », validee) :

* l'indicateur du serveur dans l'en-tete (« Serveur Beheread · connecte »,
  profil et avatar ; c'est le seul endroit ou le desktop montre un profil),
  et son menu : « Ajouter un appareil… », actualiser, preferences ;
* la provenance de chaque tome sur sa couverture (sur ce PC, sur le serveur,
  du serveur et garde hors ligne), legendee en bas de la fenetre avec
  l'espace du cache hors ligne ;
* la regle de lecture seule : les tomes du serveur ne se suppriment, ne se
  rangent et ne se corrigent pas d'ici (sauf pour l'administrateur, voir
  `can_manage_server`) ;
* les lectures des autres appareils, reportees dans la grille.

Mixin de LibraryWidget. Rien de tout cela n'apparait sans serveur Beheread."""

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from beheread.i18n import fmt_decimal, tr
from beheread.infra import servers as remote
from beheread.services import beheread_sync
from beheread.ui import icons
from beheread.ui.library.constants import WHERE_CACHED, WHERE_LOCAL, WHERE_SERVER

SERVER_BLUE = "#4a9fe8"     # maquette : « Sur le serveur »
CACHED_GREEN = "#4cc26b"    # maquette : « Serveur, garde hors ligne »
STATE_COLORS = {beheread_sync.ONLINE: "#4cc26b", beheread_sync.UPDATE: "#d9822b"}
PROGRESS_REFRESH_MS = 600   # lectures d'autres appareils regroupees
GB = 1024 ** 3

_icon_cache = {}


def where_icon(where, c):
    """Icone de provenance d'un tome (dessinee une fois par couleur)."""
    color = {WHERE_LOCAL: c["text"], WHERE_SERVER: SERVER_BLUE,
             WHERE_CACHED: CACHED_GREEN}[where]
    key = (where, color)
    if key not in _icon_cache:
        make = {WHERE_LOCAL: icons.drive, WHERE_SERVER: icons.cloud,
                WHERE_CACHED: icons.download}[where]
        _icon_cache[key] = make(color)
    return _icon_cache[key]


def where_label(where) -> str:
    return {WHERE_LOCAL: tr("Sur ce PC"), WHERE_SERVER: tr("Sur le serveur"),
            WHERE_CACHED: tr("Serveur, gardé hors ligne")}[where]


def _gb(n) -> str:
    return fmt_decimal(n / GB, 1)


def _avatar(name, color, size=24) -> QPixmap:
    """Pastille du profil : sa couleur et son initiale."""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color) if QColor(color).isValid() else QColor("#6e2e2e"))
    p.drawEllipse(0, 0, size, size)
    if name:
        font = QFont()
        font.setPixelSize(int(size * 0.5))
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor("#f5f0ee"))
        p.drawText(0, 0, size, size, Qt.AlignCenter, name[:1].upper())
    p.end()
    return pm


class BeheReadMixin:
    def _init_beheread(self):
        # Beheread Admin (J6) : l'administrateur gere aussi les tomes du serveur
        self.can_manage_server = False
        self._remote_keys = set()
        self._remote_timer = QTimer(self, singleShot=True, interval=PROGRESS_REFRESH_MS)
        self._remote_timer.timeout.connect(self._apply_remote_progress)
        self._update_shown = set()

    # ----- etat
    def _beheread_ids(self) -> list:
        if self.servers is None or not self.servers.enabled():
            return []
        return [c.id for c in self.servers.configs() if c.kind == "beheread"]

    def _main_sync(self):
        ids = self._beheread_ids()
        return self.servers.sync(ids[0]) if ids else None

    def _is_beheread(self, path) -> bool:
        if not remote.is_remote(path) or self.servers is None:
            return False
        config = self.servers.config(remote.split_path(path)[0])
        return config is not None and config.kind == "beheread"

    def _server_where(self, path):
        """Provenance affichee d'un tome, ou None sans serveur Beheread."""
        if not self._beheread_ids() or self.is_remote_source():
            return None
        if not self._is_beheread(path):
            return None if remote.is_remote(path) else WHERE_LOCAL
        offline = self.servers.offline
        return WHERE_CACHED if offline is not None and offline.is_kept(path) else WHERE_SERVER

    def _server_locked(self, paths) -> bool:
        """Lecture seule : un tome du serveur Beheread parmi `paths`."""
        return not self.can_manage_server and any(self._is_beheread(p) for p in paths)

    # ----- en-tete : indicateur du serveur
    def _build_server_pill(self):
        self.server_pill = QPushButton()
        self.server_pill.setObjectName("serverPill")
        self.server_pill.setCursor(Qt.PointingHandCursor)
        self.server_pill.setFocusPolicy(Qt.TabFocus)
        self.server_pill.clicked.connect(self._show_server_menu)
        row = QHBoxLayout(self.server_pill)
        row.setContentsMargins(12, 0, 4, 0)
        row.setSpacing(8)
        self._pill_dot = QLabel()
        self._pill_dot.setFixedSize(8, 8)
        self._pill_text = QLabel()
        self._pill_text.setObjectName("pillText")
        self._pill_text.setTextFormat(Qt.PlainText)
        self._pill_sep = QFrame()
        self._pill_sep.setObjectName("pillSep")
        self._pill_sep.setFixedSize(1, 18)
        self._pill_name = QLabel()
        self._pill_name.setObjectName("pillText")
        self._pill_name.setTextFormat(Qt.PlainText)
        self._pill_avatar = QLabel()
        self._pill_avatar.setFixedSize(24, 24)
        for w in (self._pill_dot, self._pill_text, self._pill_sep, self._pill_name,
                  self._pill_avatar):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.addWidget(w)
        self.server_pill.setFixedHeight(32)
        self.server_pill.hide()
        return self.server_pill

    def server_ui_css(self, c) -> str:
        return f"""
            QPushButton#serverPill {{ background: {c['panel']}; border: 1px solid {c['border']};
                                      border-radius: 16px; }}
            QPushButton#serverPill:hover {{ background: {c['button']}; }}
            QPushButton#serverPill:focus {{ border-color: {c['text_dim']}; }}
            #pillText {{ color: {c['text']}; }}
            #pillSep {{ background: {c['border']}; }}
        """

    def _refresh_server_pill(self):
        sync = self._main_sync()
        self.server_pill.setVisible(sync is not None)
        if sync is None:
            return
        state = sync.state
        label = {beheread_sync.ONLINE: tr("connecté"), beheread_sync.OFFLINE: tr("hors ligne"),
                 beheread_sync.UPDATE: tr("mise à jour requise"),
                 beheread_sync.CONNECTING: tr("connexion…")}[state]
        name = tr("Serveur Beheread")
        if len(self._beheread_ids()) > 1:
            config = self.servers.config(sync.server_id)
            name = config.name if config is not None else name
        self._pill_text.setText(f"{name} · {label}")
        color = STATE_COLORS.get(state, "#8b93a1")
        self._pill_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        profile = sync.profile or sync._state.get("profile") or {}
        profile_name = str(profile.get("name") or "")
        self._pill_name.setText(profile_name)
        self._pill_avatar.setPixmap(_avatar(profile_name, str(profile.get("color") or "")))
        for w in (self._pill_sep, self._pill_name, self._pill_avatar):
            w.setVisible(bool(profile_name))
        tip = tr("Serveur Beheread, connecté avec le profil {name}", name=profile_name) \
            if state == beheread_sync.ONLINE and profile_name else (sync.error or "")
        self.server_pill.setToolTip(tip)
        self.server_pill.setAccessibleName(f"{name} · {label}" +
                                           (f" · {profile_name}" if profile_name else ""))
        # un bouton ne prend pas la taille de ce que contient sa mise en page
        self.server_pill.setFixedWidth(self.server_pill.layout().sizeHint().width())
        self._balance_header()

    def _show_server_menu(self):
        from beheread.ui.library.menus import ActionMenu
        sync = self._main_sync()
        if sync is None:
            return
        m = ActionMenu(self)
        if sync.state == beheread_sync.UPDATE:
            m.add(tr("Mettre à jour Beheread…"),
                  lambda: self._show_update_required(sync.server_id, force=True), default=True)
        m.add(tr("Ajouter un appareil…"), self._add_device).setEnabled(
            sync.state == beheread_sync.ONLINE)
        m.add(tr("Actualiser"), lambda: (sync.retry(), self.servers.fetch(sync.server_id)))
        m.separator()
        m.add(tr("Préférences…"), self.open_preferences)
        m.exec(self.server_pill.mapToGlobal(self.server_pill.rect().bottomLeft()))

    def _add_device(self):
        from beheread.ui.library.server_dialogs import AddDeviceDialog
        sync = self._main_sync()
        if sync is None:
            return
        AddDeviceDialog(sync, self.servers.config(sync.server_id), self).exec()

    def _on_update_required(self, server_id):
        self._refresh_server_pill()
        self._show_update_required(server_id)

    def _show_update_required(self, server_id, force=False):
        """Fenetre « Mettez Beheread a jour » (maquette validee), une fois par
        session et par version demandee, sauf a la demande (menu)."""
        from beheread.ui.library.server_dialogs import UpdateRequiredDialog
        sync = self.servers.sync(server_id) if self.servers is not None else None
        update = sync.update if sync is not None else None
        if update is None:
            return
        key = (server_id, update.minimum)
        if key in self._update_shown and not force:
            return
        self._update_shown.add(key)
        UpdateRequiredDialog(self.servers.config(server_id), update, self).exec()

    # ----- legende et cache hors ligne
    def _build_server_footer(self):
        self.server_footer = QFrame()
        self.server_footer.setObjectName("serverFooter")
        row = QHBoxLayout(self.server_footer)
        row.setContentsMargins(20, 8, 20, 8)
        row.setSpacing(22)
        self._legend_icons = {}
        for where in (WHERE_LOCAL, WHERE_SERVER, WHERE_CACHED):
            item = QWidget()
            h = QHBoxLayout(item)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            icon = QLabel()
            icon.setFixedSize(13, 13)
            self._legend_icons[where] = icon
            text = QLabel(where_label(where))
            text.setObjectName("footerText")
            h.addWidget(icon)
            h.addWidget(text)
            row.addWidget(item)
        row.addStretch(1)
        self._cache_label = QLabel()
        self._cache_label.setObjectName("footerText")
        row.addWidget(self._cache_label)
        self.server_footer.hide()
        return self.server_footer

    def _style_server_footer(self, c):
        self.server_footer.setStyleSheet(
            f"#serverFooter {{ background: {c['window']}; border-top: 1px solid {c['border']}; }}"
            f"#footerText {{ color: {c['text_dim']}; }}")
        for where, label in self._legend_icons.items():
            label.setPixmap(where_icon(where, c).pixmap(QSize(13, 13)))

    def _refresh_server_footer(self):
        on = bool(self._beheread_ids()) and not self.is_remote_source()
        self.server_footer.setVisible(on)
        offline = self.servers.offline if self.servers is not None else None
        if not on or offline is None:
            return
        self._cache_label.setText(tr("Cache hors ligne : {used} Go sur {budget} Go",
                                     used=_gb(offline.used()), budget=_gb(offline.budget())))

    def _refresh_server_ui(self):
        self._refresh_server_pill()
        self._refresh_server_footer()

    def offline_plan(self):
        """Pour le cache hors ligne : (infos des tomes, tomes du serveur par
        empreinte, masquages de « Continuer la lecture »)."""
        if self.is_remote_source():
            raise RuntimeError("bibliotheque d'un autre serveur affichee")
        books = {}
        for path in self._info:
            if self._is_beheread(path):
                book = remote.registry.book(path)
                if book is not None:
                    books[self.store.key_for(path)] = book
        return list(self._info.values()), books, self.store.continue_dismissed()

    # ----- services
    def _connect_beheread(self, manager):
        manager.syncChanged.connect(lambda _sid: self._refresh_server_ui())
        manager.changed.connect(self._connect_offline)
        manager.changed.connect(self._refresh_server_ui)
        manager.updateRequired.connect(self._on_update_required)
        manager.progressChanged.connect(self._on_remote_progress)
        manager.listed.connect(lambda sid, _b, _e: self._schedule_offline(sid))
        self._connect_offline()
        self._refresh_server_ui()

    def _connect_offline(self):
        offline = self.servers.offline if self.servers is not None else None
        if offline is None or offline.provider is not None:
            return
        offline.provider = self.offline_plan
        offline.changed.connect(self._on_offline_changed)
        offline.schedule()

    def _schedule_offline(self, server_id):
        if self.servers.offline is not None and server_id in self._beheread_ids():
            self.servers.offline.schedule()

    def _on_offline_changed(self):
        self._refresh_server_footer()
        self.update_progress_display(list(self._path_to_item))   # icones de provenance

    def _on_remote_progress(self, key):
        self._remote_keys.add(key)
        self._remote_timer.start()

    def _apply_remote_progress(self):
        keys, self._remote_keys = self._remote_keys, set()
        paths = [p for p in self._info if self.store.key_for(p) in keys]
        if paths:
            self.update_progress_display(paths)
        if self.servers is not None and self.servers.offline is not None:
            self.servers.offline.schedule()   # tome en cours ailleurs : a garder ici

    def _remote_reader_text(self, path):
        """« lu sur l'iPad » pour une progression venue d'un autre appareil."""
        entry = self.store.progress_entry(path)
        sync = self._main_sync()
        if not entry or not entry.get("device") or sync is None:
            return ""
        name = sync.device_name(entry["device"])
        return tr("lu sur {device}", device=name) if name else ""
