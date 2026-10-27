"""Preferences > Serveurs : serveurs de lecture (Komga, Kavita, OPDS), leur
ajout et leur modification (voir la maquette 6 validee). L'option est
desactivee par defaut : tant qu'elle ne l'est pas, Beheread ne contacte
aucun serveur."""

import platform
import uuid

from PySide6.QtCore import QSize, Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from beheread import platforms
from beheread.i18n import tr, trn
from beheread.infra import servers as remote
from beheread.infra.servers import ServerConfig, ServerError
from beheread.ui.library.workers import CallWorker

GREEN, GREY, RED = "#3fa35f", "#8b93a1", "#c0392b"


def _dot(color):
    dot = QLabel()
    dot.setFixedSize(8, 8)
    dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
    return dot


class ServersTabMixin:
    """Carte « Serveurs de lecture » de PreferencesDialog (self.store, self.servers)."""

    def _servers_tab(self):
        w, v = self._page()
        s = self.store
        g = QGroupBox(tr("Serveurs de bandes dessinées"))
        gv = QVBoxLayout(g)
        gv.addWidget(self._hint(tr("Lisez les tomes de votre serveur personnel (OPDS, Komga, "
                                   "Kavita) avec le lecteur de Beheread, sans les copier sur "
                                   "cet ordinateur.")))
        self.servers_enabled = QCheckBox(tr("Activer les serveurs de lecture"))
        self.servers_enabled.setChecked(bool(s.ui_pref("servers_enabled", False)))
        gv.addWidget(self.servers_enabled)
        gv.addWidget(self._hint(tr("Désactivée, Beheread ne contacte aucun serveur.")))

        self.server_list = QListWidget()
        self.server_list.setObjectName("serverList")
        self.server_list.setMinimumHeight(120)
        self.server_list.itemDoubleClicked.connect(lambda _i: self._edit_server())
        gv.addWidget(self.server_list)
        row = QHBoxLayout()
        self.server_add = QPushButton(tr("Ajouter…"))
        self.server_add.clicked.connect(self._add_server)
        self.server_edit = QPushButton(tr("Modifier…"))
        self.server_edit.clicked.connect(self._edit_server)
        self.server_remove = QPushButton(tr("Retirer"))
        self.server_remove.clicked.connect(self._remove_server)
        for btn in (self.server_add, self.server_edit, self.server_remove):
            row.addWidget(btn)
        row.addStretch(1)
        gv.addLayout(row)
        self.servers_sync = QCheckBox(tr("Synchroniser la progression avec Komga et Kavita : une "
                                         "page lue ici est retrouvée sur le serveur, et "
                                         "inversement."))
        self.servers_sync.setChecked(bool(s.ui_pref("servers_sync", True)))
        gv.addWidget(self.servers_sync)
        v.addWidget(g)
        v.addStretch(1)

        self.servers_enabled.toggled.connect(self._update_server_buttons)
        self.server_list.currentRowChanged.connect(lambda _r: self._update_server_buttons())
        if self.servers is not None:
            self.servers.listed.connect(self._on_servers_listed)   # deconnecte avec le dialogue
        self._refresh_server_list()
        return w

    def _on_servers_listed(self, *_args):
        self._refresh_server_list()

    def _server_configs(self):
        found = (ServerConfig.from_dict(d) for d in self.store.servers())
        return [c for c in found if c is not None]

    def _refresh_server_list(self):
        current = self._selected_server_id()
        self.server_list.clear()
        for config in self._server_configs():
            books = self.servers.books(config.id) if self.servers is not None else None
            error = self.servers.error(config.id) if self.servers is not None else ""
            if error:
                color, state = GREY, tr("hors ligne")
            elif books is not None:
                color, state = GREEN, tr("connecté")
            else:
                color, state = GREY, tr("pas encore consulté")
            item = QListWidgetItem()
            item.setData(Qt.UserRole, config.id)
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 6, 10, 6)
            h.setSpacing(10)
            h.addWidget(_dot(color))
            text = QVBoxLayout()
            text.setSpacing(1)
            name = QLabel(config.name)
            name.setTextFormat(Qt.PlainText)
            name.setStyleSheet("font-weight: 600;")
            detail = QLabel(" · ".join((tr(remote.KIND_LABELS[config.kind]), config.url, state)))
            detail.setTextFormat(Qt.PlainText)
            detail.setObjectName("hint")
            if error:
                detail.setToolTip(error)
            text.addWidget(name)
            text.addWidget(detail)
            h.addLayout(text, 1)
            if books is not None:
                count = QLabel(trn(len(books), "{n} tome", "{n} tomes"))
                count.setObjectName("hint")
                h.addWidget(count)
            item.setSizeHint(QSize(0, row.sizeHint().height()))
            self.server_list.addItem(item)
            self.server_list.setItemWidget(item, row)
            if config.id == current:
                self.server_list.setCurrentItem(item)
        self._update_server_buttons()

    def _selected_server_id(self):
        item = self.server_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _update_server_buttons(self):
        on = self.servers_enabled.isChecked()
        selected = self._selected_server_id() is not None
        self.server_list.setEnabled(on)
        self.server_add.setEnabled(on)
        self.server_edit.setEnabled(on and selected)
        self.server_remove.setEnabled(on and selected)
        self.servers_sync.setEnabled(on)

    def _add_server(self):
        dlg = ServerDialog(self.store, None, self)
        if dlg.exec() == QDialog.Accepted:
            self._servers_changed()

    def _edit_server(self):
        sid = self._selected_server_id()
        config = next((c for c in self._server_configs() if c.id == sid), None)
        if config is None or not self.servers_enabled.isChecked():
            return
        dlg = ServerDialog(self.store, config, self)
        if dlg.exec() == QDialog.Accepted:
            self._servers_changed()

    def _remove_server(self):
        sid = self._selected_server_id()
        config = next((c for c in self._server_configs() if c.id == sid), None)
        if config is None:
            return
        if self._confirm(tr("Retirer le serveur"),
                         tr("Retirer « {name} » de Beheread ? Rien n'est supprimé sur le "
                            "serveur.", name=config.name)):
            self.store.remove_server(sid)
            self._servers_changed()

    def _servers_changed(self):
        if self.servers is not None:
            self.servers.reload()
        self._refresh_server_list()
        self._refresh_cards()   # etat de la carte « Serveurs de lecture »

    def _save_servers(self):
        s = self.store
        s.set_ui_pref("servers_enabled", self.servers_enabled.isChecked())
        s.set_ui_pref("servers_sync", self.servers_sync.isChecked())


class ServerDialog(QDialog):
    """Ajout ou modification d'un serveur, avec essai de la connexion."""

    def __init__(self, store, config=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.config = config
        self._call = None
        self.setWindowTitle(tr("Modifier le serveur") if config else tr("Ajouter un serveur"))
        self.setMinimumWidth(480)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        title = QLabel(self.windowTitle())
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(title)
        f = QFormLayout()
        self.kind = QComboBox()
        for kind in remote.KINDS:
            self.kind.addItem(tr(remote.KIND_LABELS[kind]), kind)
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("http://192.168.1.20:25600")
        self.user = QLineEdit()
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.Password)
        # serveur Beheread : lien d'invitation, ou code « Ajouter un appareil »
        self.invite = QLineEdit()
        self.invite.setPlaceholderText("https://mangas.exemple.fr/i/K7M2QX9P")
        self.invite.textChanged.connect(self._on_invite_changed)
        self.form = f
        f.addRow(tr("Type"), self.kind)
        f.addRow(tr("Lien ou code"), self.invite)
        f.addRow(tr("Nom affiché"), self.name)
        f.addRow(tr("Adresse"), self.url)
        f.addRow(tr("Identifiant"), self.user)
        f.addRow(tr("Mot de passe ou clé d'API"), self.secret)
        root.addLayout(f)
        self.beheread_hint = self._hint(
            tr("Collez le lien d'invitation reçu, ou le code affiché par « Ajouter un appareil » "
               "sur un de vos appareils déjà connectés (l'adresse du serveur est alors à saisir). "
               "Votre progression sera la même sur tous vos appareils."))
        root.addWidget(self.beheread_hint)
        self.secret_hint = self._hint(
            tr("Le mot de passe est chiffré dans le Trousseau de ce Mac, comme la connexion "
               "AniList.") if platforms.IS_MACOS else
            tr("Le mot de passe est chiffré par Windows, comme la connexion AniList."))
        root.addWidget(self.secret_hint)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.PlainText)   # message du serveur : non fiable
        self.result.hide()
        root.addWidget(self.result)
        row = QHBoxLayout()
        self.test_btn = QPushButton(tr("Tester la connexion"))
        self.test_btn.clicked.connect(self._test)
        cancel = QPushButton(tr("Annuler"))
        cancel.clicked.connect(self.reject)
        self.ok_btn = QPushButton(tr("Enregistrer") if config else tr("Ajouter"))
        self.ok_btn.setObjectName("primary")
        self.ok_btn.clicked.connect(self._accept)
        row.addWidget(self.test_btn)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(self.ok_btn)
        root.addLayout(row)

        if config is not None:
            self.kind.setCurrentIndex(max(0, self.kind.findData(config.kind)))
            self.name.setText(config.name)
            self.url.setText(config.url)
            self.user.setText(config.user)
            self.secret.setPlaceholderText(tr("inchangé"))
        self.kind.currentIndexChanged.connect(lambda _i: self._update_fields())
        self._update_fields()

    @staticmethod
    def _hint(text):
        lab = QLabel(text)
        lab.setObjectName("hint")
        lab.setWordWrap(True)
        return lab

    def _beheread(self) -> bool:
        return self.kind.currentData() == "beheread"

    def _on_invite_changed(self, text):
        url, _code = remote.parse_invitation(text)
        if url:
            self.url.setText(url)

    def _update_fields(self):
        beheread = self._beheread()
        # deja connecte (modification) : le jeton reste, pas de nouveau code
        self.form.setRowVisible(self.invite, beheread and self.config is None)
        self.form.setRowVisible(self.user, not beheread)
        self.form.setRowVisible(self.secret, not beheread)
        self.beheread_hint.setVisible(beheread and self.config is None)
        self.secret_hint.setVisible(not beheread)
        self.url.setPlaceholderText("https://mangas.exemple.fr" if beheread
                                    else "http://192.168.1.20:25600")
        kavita = self.kind.currentData() == "kavita"
        self.user.setEnabled(not kavita)
        self.user.setPlaceholderText(
            tr("inutile pour Kavita") if kavita else
            tr("vide avec une clé d'API") if self.kind.currentData() == "komga" else
            tr("si le serveur en demande un"))

    def _current(self):
        """(ServerConfig, secret ou None pour garder l'actuel) d'apres les champs.
        Leve ServerError si l'adresse n'est pas exploitable."""
        url = remote.normalize_url(self.url.text())
        sid = self.config.id if self.config is not None else uuid.uuid4().hex[:16]
        kind = self.kind.currentData()
        config = ServerConfig(id=sid, kind=kind, name=self.name.text().strip() or url, url=url,
                              user="" if kind == "kavita" else self.user.text().strip())
        secret = self.secret.text()
        if not secret and self.config is not None:
            secret = None
        return config, secret

    def _show_result(self, text, ok):
        self.result.setText(("✓ " if ok else "") + text)
        self.result.setStyleSheet(f"color: {GREEN if ok else RED};")
        self.result.show()

    def _invitation(self):
        """(adresse, code) saisis pour un serveur Beheread ; leve ServerError."""
        url, code = remote.parse_invitation(self.invite.text())
        url = remote.normalize_url(url or self.url.text())
        if len(code) != 8:
            raise ServerError(tr("Collez le lien d'invitation, ou un code de 8 caractères."))
        return url, code

    def _test(self):
        try:
            config, secret = self._current()
            invitation = self._invitation() if self._beheread() and self.config is None else None
        except ServerError as e:
            self._show_result(str(e), False)
            return
        if secret is None:
            secret = self.store.server_secret(config.id) or ""
        self.test_btn.setEnabled(False)
        self._show_result(tr("Connexion en cours…"), True)
        self.result.setStyleSheet("")
        if invitation is not None:
            # sans consommer l'invitation : on ne fait que la lire
            self._call = CallWorker(lambda: remote.preview_invitation(*invitation))
        else:
            self._call = CallWorker(lambda: remote.make_client(config, secret).check())
        self._call.signals.done.connect(self._on_tested)
        QThreadPool.globalInstance().start(self._call)

    def _on_tested(self, result, err):
        self._call = None
        self.test_btn.setEnabled(True)
        if err is not None:
            self._show_result(str(err) if isinstance(err, ServerError)
                              else tr("Réponse inattendue du serveur."), False)
            return
        parts = [tr("Connexion réussie"), result.get("version") or ""]
        if isinstance(result.get("count"), int):
            parts.append(trn(result["count"], "{n} tome", "{n} tomes"))
        self._show_result(" · ".join(p for p in parts if p), True)

    def _accept(self):
        try:
            config, secret = self._current()
            invitation = self._invitation() if self._beheread() and self.config is None else None
        except ServerError as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return
        if invitation is None:
            self.store.save_server(config.to_dict(), secret)
            self.accept()
            return
        # serveur Beheread : cet ordinateur est lie au profil de l'invitation
        url, code = invitation
        config.url = url
        self.ok_btn.setEnabled(False)
        self._show_result(tr("Connexion en cours…"), True)
        self.result.setStyleSheet("")
        self._call = CallWorker(lambda: remote.enroll(url, code, platform.node() or "PC"))
        self._call.signals.done.connect(lambda result, err: self._on_enrolled(config, result, err))
        QThreadPool.globalInstance().start(self._call)

    def _on_enrolled(self, config, result, err):
        self._call = None
        self.ok_btn.setEnabled(True)
        if err is not None:
            self._show_result(str(err) if isinstance(err, ServerError)
                              else tr("Réponse inattendue du serveur."), False)
            return
        token, profile = result
        if not self.name.text().strip() and profile.get("name"):
            config.name = tr("Serveur Beheread · {name}", name=profile["name"])
        self.store.save_server(config.to_dict(), token)
        self.accept()

    def done(self, result):
        if self._call is not None:   # essai en cours : la reponse sera ignoree
            self._call.signals.done.disconnect()
            self._call = None
        super().done(result)
