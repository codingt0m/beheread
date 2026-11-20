"""Bandeau de reprise du lecteur (maquette « Reprise dans le lecteur du
desktop », validee) : un tome lu plus loin sur un autre appareil s'ouvre a
cette page, et le bandeau propose de revenir a la page lue ici auparavant.
Un repere gris marque cette page sur la barre de position.

Mixin de ReaderWidget. Le bandeau s'efface seul apres quelques secondes
(sauf pendant le survol), ou par sa croix."""

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from beheread.core.sync import ago
from beheread.i18n import tr
from beheread.ui import icons, theme

RESUME_SHOW_MS = 8000
RESUME_TOP = 60
RESUME_ICON = "#4a9fe8"   # bleu de la maquette (icone « sur le serveur »)


def _resume_icon(color) -> QIcon:
    """Fleche circulaire (reprise)."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 5.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawArc(10, 10, 44, 44, 40 * 16, 290 * 16)
    p.drawLine(QPointF(54, 8), QPointF(54, 22))
    p.drawLine(QPointF(54, 22), QPointF(40, 22))
    p.end()
    return QIcon(pm)


class _Banner(QFrame):
    """Le bandeau lui-meme : il retient le survol (pas d'effacement)."""

    def __init__(self, parent, on_hover):
        super().__init__(parent)
        self._on_hover = on_hover

    def event(self, e):
        if e.type() in (QEvent.Enter, QEvent.Leave):
            self._on_hover(e.type() == QEvent.Enter)
        return super().event(e)


class ResumeMixin:
    def _build_resume_banner(self):
        self.resume_banner = _Banner(self, self._on_resume_hover)
        self.resume_banner.setObjectName("resumeBanner")
        self.resume_banner.setAccessibleName(tr("Reprise de la lecture"))
        row = QHBoxLayout(self.resume_banner)
        row.setContentsMargins(16, 8, 8, 8)
        row.setSpacing(12)
        self._resume_icon = QLabel()
        row.addWidget(self._resume_icon)
        self._resume_text = QLabel()
        self._resume_text.setObjectName("resumeText")
        self._resume_text.setTextFormat(Qt.PlainText)
        row.addWidget(self._resume_text)
        self._resume_back = QPushButton()
        self._resume_back.setObjectName("resumeBack")
        self._resume_back.setCursor(Qt.PointingHandCursor)
        self._resume_back.setFocusPolicy(Qt.NoFocus)
        self._resume_back.clicked.connect(self._resume_go_back)
        row.addWidget(self._resume_back)
        self._resume_close = QPushButton()
        self._resume_close.setObjectName("resumeClose")
        self._resume_close.setCursor(Qt.PointingHandCursor)
        self._resume_close.setFocusPolicy(Qt.NoFocus)
        self._resume_close.setAccessibleName(tr("Fermer le bandeau"))
        self._resume_close.clicked.connect(self.hide_resume)
        row.addWidget(self._resume_close)
        self.resume_banner.hide()
        self._resume_page = None     # page lue ici avant la reprise
        self._opened_page = self.page   # page d'ouverture (voir resume_to)
        self._resume_timer = QTimer(self, singleShot=True, interval=RESUME_SHOW_MS)
        self._resume_timer.timeout.connect(self.hide_resume)

    def _style_resume_banner(self, c):
        self._resume_icon.setPixmap(_resume_icon(RESUME_ICON).pixmap(16, 16))
        self._resume_close.setIcon(icons.x_mark(c["text_dim"]))
        self.resume_banner.setStyleSheet(
            f"#resumeBanner {{ background: {c['button']}; border: 1px solid {c['button_hover']};"
            " border-radius: 8px; }"
            f"#resumeText {{ color: {c['text']}; font-size: 14px; }}"
            f"QPushButton#resumeBack {{ color: {theme.ACCENT}; background: {c['button_hover']};"
            " border: none; border-radius: 6px; padding: 8px 12px; font-weight: 600; }"
            f"QPushButton#resumeBack:hover {{ background: {c['border']}; }}"
            "QPushButton#resumeClose { background: transparent; border: none;"
            " border-radius: 6px; padding: 8px; }"
            f"QPushButton#resumeClose:hover {{ background: {c['button_hover']}; }}")

    def resume_to(self, page: int, back_to: int, device_name: str, ts: float) -> bool:
        """Progression arrivee d'un autre appareil pendant que ce tome est
        ouvert : saute a `page` si la lecture n'a pas encore commence ici
        (toujours sur la page d'ouverture). Renvoie True si c'est fait."""
        if self.page != self._opened_page or not 0 <= page < self.total or page == self.page:
            return False
        self._go_to(page, save=False, animate=False)
        self._opened_page = self.page
        self.show_resume(back_to, device_name, ts)
        return True

    def show_resume(self, back_to: int, device_name: str, ts: float):
        """Bandeau « Repris a la page 87, lue sur l'iPad il y a 5 min ·
        Revenir page 40 » pour la page courante (deja atteinte)."""
        if not 0 <= back_to < self.total or back_to == self.page:
            return
        self._resume_page = back_to
        when = ago(ts)
        if device_name:
            text = tr("Repris à la page {page}, lue sur {device} {when}",
                      page=self.page + 1, device=device_name, when=when)
        else:
            text = tr("Repris à la page {page}, lue sur un autre appareil {when}",
                      page=self.page + 1, when=when)
        self._resume_text.setText(text)
        self._resume_back.setText(tr("Revenir page {page}", page=back_to + 1))
        self.page_slider.set_back_marker(back_to)
        self.resume_banner.adjustSize()
        self._place_resume_banner()
        self.resume_banner.show()
        self.resume_banner.raise_()
        self._resume_timer.start()

    def hide_resume(self):
        self._resume_timer.stop()
        self.resume_banner.hide()
        self.page_slider.set_back_marker(None)
        self._resume_page = None

    def _resume_go_back(self):
        page = self._resume_page
        self.hide_resume()
        if page is not None:
            self._go_to(page)   # la progression repart vers le serveur

    def _on_resume_hover(self, inside):
        if inside:
            self._resume_timer.stop()
        elif self.resume_banner.isVisible():
            self._resume_timer.start()

    def _place_resume_banner(self):
        b = self.resume_banner
        b.move(max(8, (self.width() - b.width()) // 2), RESUME_TOP)
