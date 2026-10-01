"""Panneau d'informations a droite de la bibliotheque : couverture, auteur,
annee, progression, fichier... de l'element selectionne, avec ses actions
principales. Jusqu'ici ces informations n'etaient visibles qu'au survol.

Le panneau est passif : la bibliotheque lui fournit un contenu tout pret
(show_content) et les actions a proposer (libelle + fonction)."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from beheread.ui import theme

PANEL_W = 300
COVER_W = 190
TITLE_MAX_CHARS = 90

# separateurs courants des noms de fichiers : apres eux, un espace de largeur
# nulle autorise le retour a la ligne (« Berserk_ch0364[FR][TEAM] »)
_BREAK_AFTER = "_-.,)]}/\\"
_ZWSP = "\u200b"
_MAX_RUN = 14   # au-dela, un bloc sans aucune coupure possible est coupe quand meme


def breakable(text: str) -> str:
    """Texte qui peut revenir a la ligne meme sans espace (sinon un long nom
    de fichier elargirait le panneau au lieu de passer a la ligne)."""
    out, run = [], 0
    for ch in text:
        out.append(ch)
        if ch.isspace():
            run = 0
        elif ch in _BREAK_AFTER or run + 1 >= _MAX_RUN:
            out.append(_ZWSP)
            run = 0
        else:
            run += 1
    return "".join(out)


def shorten(text: str, limit: int = TITLE_MAX_CHARS) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


class ElidedButton(QPushButton):
    """Bouton dont le libelle est raccourci (« … ») a la largeur disponible,
    le texte complet restant en infobulle : un libelle long (titre de tome)
    n'impose plus sa largeur au panneau."""

    PADDING = 34   # marges internes + bordure (feuille de style du panneau)

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def full_text(self):
        return self._full

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        avail = max(0, self.width() - self.PADDING)
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideRight, avail))


class DetailPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("detailPanel")
        self.setFixedWidth(PANEL_W)
        self.setAccessibleName("Informations")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("detailScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        host = QWidget()
        host.setObjectName("detailHost")
        # le contenu suit la largeur du panneau et ne l'impose jamais (textes
        # secables via breakable(), boutons raccourcis via ElidedButton) ; la
        # hauteur suit le contenu replie (hauteur-pour-largeur de la zone)
        host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        scroll.setWidget(host)

        self._v = QVBoxLayout(host)
        self._v.setSizeConstraint(QLayout.SetNoConstraint)
        self._v.setContentsMargins(20, 20, 20, 20)
        self._v.setSpacing(10)

        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignCenter)
        self._v.addWidget(self.cover)

        self.title = QLabel()
        self.title.setObjectName("detailTitle")
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._v.addWidget(self.title)

        self.subtitle = QLabel()
        self.subtitle.setObjectName("detailSub")
        self.subtitle.setWordWrap(True)
        self._v.addWidget(self.subtitle)

        self.form = QFormLayout()
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(6)
        self.form.setLabelAlignment(Qt.AlignLeft)
        self._v.addLayout(self.form)

        self._actions_box = QVBoxLayout()
        self._actions_box.setSpacing(6)
        self._v.addSpacing(6)
        self._v.addLayout(self._actions_box)
        self._v.addStretch(1)

        self.placeholder = QLabel("Sélectionnez un manga ou une série pour afficher "
                                  "ses informations.")
        self.placeholder.setObjectName("detailSub")
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(Qt.AlignCenter)
        self._v.insertWidget(0, self.placeholder)
        self.clear()

    # ----- contenu -----
    def clear(self):
        self._set_visible_content(False)
        self.placeholder.show()

    def _set_visible_content(self, visible):
        for w in (self.cover, self.title, self.subtitle):
            w.setVisible(visible)
        self._clear_form()
        self._clear_actions()

    def _clear_form(self):
        while self.form.rowCount():
            self.form.removeRow(0)

    def _clear_actions(self):
        while self._actions_box.count():
            w = self._actions_box.takeAt(0).widget()
            if w is not None:
                w.hide()          # detruit plus tard : ne doit plus s'afficher d'ici la
                w.deleteLater()

    def show_content(self, cover: QPixmap, title: str, subtitle: str, rows, actions):
        """rows : [(libelle, valeur)] (valeurs vides ignorees) ;
        actions : [(libelle, fonction, principale)]."""
        self.placeholder.hide()
        self._set_visible_content(True)
        self.set_cover(cover)
        self.title.setText(breakable(shorten(title)))
        self.title.setToolTip(title if len(title) > TITLE_MAX_CHARS else "")
        self.subtitle.setText(breakable(subtitle))
        self.subtitle.setVisible(bool(subtitle))
        for label, value in rows:
            if not value:
                continue
            k = QLabel(label)
            k.setObjectName("detailKey")
            val = QLabel(value)
            val.setObjectName("detailVal")
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.form.addRow(k, val)
        for label, fn, primary in actions:
            b = ElidedButton(label)
            b.setObjectName("detailPrimary" if primary else "detailAction")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            self._actions_box.addWidget(b)

    def set_cover(self, pm):
        if pm is None or pm.isNull():
            self.cover.clear()
            self.cover.setFixedSize(QSize(COVER_W, round(COVER_W * 1.41)))
            return
        dpr = self.devicePixelRatioF()
        scaled = pm.scaled(QSize(round(COVER_W * dpr), round(COVER_W * 1.6 * dpr)),
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        self.cover.setFixedSize(QSize(round(scaled.width() / dpr), round(scaled.height() / dpr)))
        self.cover.setPixmap(scaled)

    def apply_colors(self, c):
        self.setStyleSheet(f"""
            #detailPanel {{ background: {c['panel']}; border-left: 1px solid {c['border']}; }}
            #detailScroll, #detailHost {{ background: {c['panel']}; border: none; }}
            #detailTitle {{ color: {c['text']}; font-size: 17px; font-weight: 700; }}
            #detailSub {{ color: {c['text_dim']}; font-size: 13px; }}
            #detailKey {{ color: {c['text_dim']}; font-size: 12px; }}
            #detailVal {{ color: {c['text']}; font-size: 12px; }}
            QPushButton#detailPrimary {{
                color: {theme.ON_ACCENT}; background: {theme.ACCENT}; border: none;
                border-radius: 8px; padding: 8px 14px; font-size: 13px; font-weight: 700;
            }}
            QPushButton#detailPrimary:hover {{ background: {theme.ACCENT_HOVER}; }}
            QPushButton#detailAction {{
                color: {c['text']}; background: {c['button']};
                border: 1px solid {c['border']}; border-radius: 8px;
                padding: 6px 12px; font-size: 12px; text-align: left;
            }}
            QPushButton#detailAction:hover {{ background: {c['button_hover']}; }}
            QPushButton:focus {{ border: 2px solid {c['text']}; }}
        """)
