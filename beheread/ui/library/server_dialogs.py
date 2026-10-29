"""Fenetres du serveur Beheread (maquettes validees) : « Ajouter un
appareil » (code et QR code valables 10 minutes) et « Mettez Beheread a
jour pour lire sur ce serveur »."""

import time
import urllib.parse

from PySide6.QtCore import QRectF, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from beheread.core.sync import ago
from beheread.i18n import tr
from beheread.infra import updates
from beheread.infra.servers import ServerError
from beheread.ui import icons, theme
from beheread.ui.library.workers import CallWorker

QR_SIZE = 148
UPDATE_ICON = "#d9822b"


def qr_pixmap(text, size=QR_SIZE) -> QPixmap:
    """QR code (correction M) noir sur blanc, de `size` pixels logiques."""
    import segno
    rows = [list(r) for r in segno.make(text, error="m", micro=False).matrix]
    n = len(rows)
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#000000"))
    margin = 8
    cell = (size - 2 * margin) / n
    for y, row in enumerate(rows):
        for x, dark in enumerate(row):
            if dark:
                p.drawRect(QRectF(margin + x * cell, margin + y * cell, cell + 0.02, cell + 0.02))
    p.end()
    return pm


def _dialog_css(c) -> str:
    return f"""
        QDialog {{ background: {c['window']}; }}
        QLabel {{ color: {c['text']}; }}
        QLabel#dim {{ color: {c['text_dim']}; }}
        QLabel#title {{ font-size: 18px; font-weight: 700; }}
        #box {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px; }}
        QPushButton {{ color: {c['text']}; background: {c['button']}; border: none;
                       border-radius: 6px; padding: 7px 14px; }}
        QPushButton:hover {{ background: {c['button_hover']}; }}
        QPushButton#primary {{ color: #f5f0ee; background: {theme.ACCENT}; font-weight: 700;
                               padding: 8px 16px; }}
        QPushButton#primary:hover {{ background: {theme.ACCENT_HOVER}; }}
    """


def _label(text="", name=None, wrap=False):
    lab = QLabel(text)
    lab.setTextFormat(Qt.PlainText)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


class AddDeviceDialog(QDialog):
    """« Ajouter un appareil » depuis le desktop connecte : code valable 10
    minutes et une seule fois, son QR code, et les appareils du profil."""

    def __init__(self, sync, config, parent=None):
        super().__init__(parent)
        self.sync = sync
        self.config = config
        self._call = None
        self._expires = 0.0
        self._admin = ""
        self.setWindowTitle(tr("Ajouter un appareil"))
        self.setMinimumWidth(600)
        c = theme.colors(sync.store.ui_pref("theme", "dark"))
        self.setStyleSheet(_dialog_css(c))
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 22)
        root.setSpacing(16)
        root.addWidget(_label(tr("Ajouter un appareil"), "title"))
        root.addWidget(_label(tr("Sur votre autre appareil, ouvrez Beheread (web ou desktop), "
                                 "choisissez « J'ai un code », puis scannez ce QR code ou "
                                 "saisissez le code. Votre progression y sera la même "
                                 "qu'ici."), "dim", wrap=True))

        box = QFrame()
        box.setObjectName("box")
        row = QHBoxLayout(box)
        row.setContentsMargins(18, 18, 18, 18)
        row.setSpacing(22)
        self.qr = QLabel()
        self.qr.setFixedSize(QR_SIZE, QR_SIZE)
        self.qr.setAccessibleName(tr("QR code d'ajout d'appareil"))
        self.qr.setStyleSheet("background: #ffffff; border-radius: 6px;")
        row.addWidget(self.qr)
        col = QVBoxLayout()
        col.setSpacing(10)
        self.code = _label(tr("Code en cours…"))
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono.setPixelSize(32)
        mono.setLetterSpacing(QFont.AbsoluteSpacing, 5)
        self.code.setFont(mono)
        self.code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(self.code)
        self.validity = _label("", "dim", wrap=True)
        col.addWidget(self.validity)
        self.copy_btn = QPushButton(tr("Copier le code"))
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._copy)
        col.addWidget(self.copy_btn, 0, Qt.AlignLeft)
        col.addStretch(1)
        row.addLayout(col, 1)
        root.addWidget(box)

        root.addWidget(_label(tr("Vos appareils"), None))
        self.devices = QFrame()
        self.devices.setObjectName("box")
        self.devices_layout = QVBoxLayout(self.devices)
        self.devices_layout.setContentsMargins(12, 6, 12, 6)
        root.addWidget(self.devices)
        self.lost = _label("", "dim", wrap=True)
        root.addWidget(self.lost)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        done = QPushButton(tr("Terminé"))
        done.setObjectName("primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        buttons.addWidget(done)
        root.addLayout(buttons)

        self._tick = QTimer(self, interval=1000)
        self._tick.timeout.connect(self._update_validity)
        self._request()

    def _request(self):
        client = self.sync.client

        def work():
            return client.pair(), client.me()
        self._call = CallWorker(work)
        self._call.signals.done.connect(self._on_code)
        QThreadPool.globalInstance().start(self._call)

    def _on_code(self, result, err):
        self._call = None
        if err is not None:
            self.code.setText("— — — —")
            self.validity.setText(str(err) if isinstance(err, ServerError)
                                  else tr("Réponse inattendue du serveur."))
            return
        pair, me = result
        code = pair["code"]
        self._code = code
        self._expires = float(pair.get("expires") or time.time() + 600)
        self.code.setText(f"{code[:4]} {code[4:]}")
        url = f"{self.config.url.rstrip('/')}/i/{urllib.parse.quote(code)}" if self.config else code
        self.qr.setPixmap(qr_pixmap(url))
        self.copy_btn.setEnabled(True)
        self._fill_devices(me)
        self._update_validity()
        self._tick.start()

    def _fill_devices(self, me):
        while self.devices_layout.count():
            item = self.devices_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        kinds = {"web": tr("Web"), "desktop": tr("Desktop")}
        for d in me.get("devices") or ():
            if not isinstance(d, dict):
                continue
            line = QWidget()
            h = QHBoxLayout(line)
            h.setContentsMargins(0, 4, 0, 4)
            h.setSpacing(10)
            current = bool(d.get("current"))
            name = _label(tr("Ce PC") if current else str(d.get("name") or "?"))
            name.setStyleSheet("font-weight: 600;")
            seen = tr("connecté maintenant") if current else \
                tr("vu {when}", when=ago(d.get("last_seen")))
            h.addWidget(name)
            h.addWidget(_label(f"{kinds.get(d.get('kind'), '')} · {seen}", "dim"))
            h.addStretch(1)
            self.devices_layout.addWidget(line)
        self._admin = str(me.get("admin_name") or "")
        self.lost.setText(tr("Un appareil perdu ? Prévenez {admin} : il peut le retirer.",
                             admin=self._admin) if self._admin else "")

    def _update_validity(self):
        left = int(self._expires - time.time())
        if left <= 0:
            self._tick.stop()
            self.validity.setText(tr("Code expiré : un nouveau code arrive…"))
            self.copy_btn.setEnabled(False)
            self._request()
            return
        self.validity.setText(tr("Valable 10 minutes, une seule fois · encore {m} min {s} s",
                                 m=left // 60, s=f"{left % 60:02d}"))

    def _copy(self):
        QGuiApplication.clipboard().setText(getattr(self, "_code", ""))
        self.copy_btn.setText(tr("Code copié"))
        btn = self.copy_btn   # minuteur lie au bouton : rien si la fenetre est fermee avant
        QTimer.singleShot(1500, btn, lambda: btn.setText(tr("Copier le code")))

    def done(self, result):
        self._tick.stop()
        if self._call is not None:
            self._call.signals.done.disconnect()
            self._call = None
        super().done(result)


class UpdateRequiredDialog(QDialog):
    """« Mettez Beheread a jour pour lire sur ce serveur » : le serveur exige
    une version plus recente ; les dossiers locaux restent lisibles et la
    progression attend sur ce PC."""

    def __init__(self, config, update, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Mise à jour nécessaire"))
        self.setMinimumWidth(600)
        store = getattr(parent, "store", None)
        c = theme.colors(store.ui_pref("theme", "dark") if store is not None else "dark")
        self.setStyleSheet(_dialog_css(c))
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 22)
        root.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(14)
        icon = QLabel()
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"background: {c['button']}; border-radius: 20px;")
        icon.setPixmap(icons.download(UPDATE_ICON).pixmap(20, 20))
        top.addWidget(icon, 0, Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(6)
        texts.addWidget(_label(tr("Mettez Beheread à jour pour lire sur ce serveur"), "title",
                               wrap=True))
        host = urllib.parse.urlsplit(config.url).hostname if config is not None else ""
        texts.addWidget(_label(tr("Le serveur {host} a été mis à jour et demande la dernière "
                                  "version de Beheread.", host=host or "?"), "dim", wrap=True))
        top.addLayout(texts, 1)
        root.addLayout(top)

        box = QFrame()
        box.setObjectName("box")
        grid = QGridLayout(box)
        grid.setContentsMargins(18, 14, 18, 14)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        grid.addWidget(_label(tr("Votre version"), "dim"), 0, 0)
        grid.addWidget(_label(update.current), 0, 1)
        grid.addWidget(_label(tr("Version demandée"), "dim"), 1, 0)
        wanted = _label(update.minimum)
        wanted.setStyleSheet("font-weight: 600;")
        grid.addWidget(wanted, 1, 1)
        grid.setColumnStretch(1, 1)
        root.addWidget(box)
        root.addWidget(_label(tr("En attendant, vos dossiers locaux restent lisibles. Votre "
                                 "progression est gardée sur ce PC et partira vers le serveur "
                                 "après la mise à jour."), "dim", wrap=True))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later = QPushButton(tr("Plus tard"))
        later.clicked.connect(self.reject)
        update_btn = QPushButton(tr("Mettre à jour"))
        update_btn.setObjectName("primary")
        update_btn.setDefault(True)
        update_btn.clicked.connect(self._open_download)
        buttons.addWidget(later)
        buttons.addWidget(update_btn)
        root.addLayout(buttons)

    def _open_download(self):
        QDesktopServices.openUrl(QUrl(updates.RELEASES_PREFIX + "latest"))
        self.accept()
