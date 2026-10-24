"""Panneau d'informations a droite de la bibliotheque : couverture, auteur,
annee, progression, fichier... de l'element selectionne, avec ses actions
principales. Jusqu'ici ces informations n'etaient visibles qu'au survol.

Le panneau est passif : la bibliotheque lui fournit un contenu tout pret
(show_content) et les actions a proposer (libelle + fonction). Maquette M4
validee : une action principale, deux secondaires cote a cote, puis « ⋯ »
qui ouvre le menu contextuel de l'element (toutes les autres actions)."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from beheread.i18n import tr
from beheread.ui import style, theme
from beheread.ui.flow import FlowLayout
from beheread.ui.safe_text import plain

PANEL_W = 300
COVER_W = 96
# resume affiche replie : ses premiers caracteres, « Lire tout le resume » deplie
SUMMARY_PREVIEW = 240
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
        self.setToolTip(plain(text))
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
        self.setAccessibleName(tr("Informations"))
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

        # en-tete : petite couverture a gauche ; titre, auteur et annee,
        # genres a droite
        header = QHBoxLayout()
        header.setSpacing(14)
        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        header.addWidget(self.cover, 0, Qt.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(6)
        # titres, auteurs... viennent de sources non fiables : jamais lus
        # comme du HTML (voir beheread/ui/safe_text.py)
        self.title = QLabel()
        self.title.setObjectName("detailTitle")
        self.title.setTextFormat(Qt.PlainText)
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        names.addWidget(self.title)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("detailSub")
        self.subtitle.setTextFormat(Qt.PlainText)
        self.subtitle.setWordWrap(True)
        names.addWidget(self.subtitle)
        self.genres_host = QWidget()
        self.genres = FlowLayout(self.genres_host, spacing=6)
        names.addWidget(self.genres_host)
        names.addStretch(1)
        header.addLayout(names, 1)
        self._v.addLayout(header)

        # resume (base en ligne), replie par defaut
        self.summary = QLabel()
        self.summary.setObjectName("detailSummary")
        self.summary.setTextFormat(Qt.PlainText)
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._v.addWidget(self.summary)
        self.summary_toggle = QPushButton()
        self.summary_toggle.setObjectName("detailLink")
        self.summary_toggle.setCursor(Qt.PointingHandCursor)
        self.summary_toggle.clicked.connect(self._toggle_summary)
        self._v.addWidget(self.summary_toggle, 0, Qt.AlignLeft)
        self._summary_full = ""
        self._summary_open = False

        self.form = QFormLayout()
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(6)
        self.form.setLabelAlignment(Qt.AlignLeft)
        self._v.addLayout(self.form)

        # avertissement (recherche de metadonnees en echec) et son bouton
        self.notice = QFrame()
        self.notice.setObjectName("detailNotice")
        nv = QVBoxLayout(self.notice)
        nv.setContentsMargins(12, 10, 12, 10)
        nv.setSpacing(8)
        self.notice_text = QLabel()
        self.notice_text.setObjectName("detailNoticeText")
        self.notice_text.setTextFormat(Qt.PlainText)
        self.notice_text.setWordWrap(True)
        nv.addWidget(self.notice_text)
        self.notice_button = QPushButton()
        self.notice_button.setObjectName("detailNoticeButton")
        self.notice_button.setCursor(Qt.PointingHandCursor)
        self._notice_fn = None
        self.notice_button.clicked.connect(self._on_notice_clicked)
        nv.addWidget(self.notice_button, 0, Qt.AlignRight)
        self.notice.hide()
        self._v.addWidget(self.notice)

        self._actions_box = QVBoxLayout()
        self._actions_box.setSpacing(6)
        self._v.addSpacing(6)
        self._v.addLayout(self._actions_box)
        self._v.addStretch(1)

        self.placeholder = QLabel(tr("Sélectionnez un manga ou une série pour afficher "
                                     "ses informations."))
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
        self._set_genres(())
        self._set_summary("")
        self._clear_form()
        self._clear_actions()
        self._set_notice(None)

    def _set_notice(self, notice):
        self.notice.setVisible(notice is not None)
        if notice is None:
            self._notice_fn = None
            return
        text, button, self._notice_fn = notice
        self.notice_text.setText(text)
        self.notice_button.setText(button)

    def _on_notice_clicked(self):
        if self._notice_fn is not None:
            self._notice_fn()

    def _clear_form(self):
        while self.form.rowCount():
            self.form.removeRow(0)

    def _clear_actions(self):
        while self._actions_box.count():
            w = self._actions_box.takeAt(0).widget()
            if w is not None:
                w.hide()          # detruit plus tard : ne doit plus s'afficher d'ici la
                w.deleteLater()

    def _value_widget(self, value, link):
        """Valeur d'une ligne d'informations, suivie d'un lien (« Changer »)
        quand `link` = (libelle, fonction(position globale))."""
        val = QLabel(value)
        val.setObjectName("detailVal")
        val.setTextFormat(Qt.PlainText)
        val.setWordWrap(True)
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        val.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if link is None:
            return val
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(val, 1)
        label, fn = link
        btn = QPushButton(label)
        btn.setObjectName("detailLink")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: fn(btn.mapToGlobal(btn.rect().bottomLeft())))
        row.addWidget(btn, 0, Qt.AlignTop)
        return host

    def _add_actions(self, actions, more):
        """Principale(s) en pleine largeur ; secondaires deux par rangee, la
        derniere rangee finissant par « ⋯ » (more : fonction(position globale)
        qui ouvre le menu de l'element)."""
        secondary = []
        for label, fn, primary in actions:
            b = ElidedButton(label)
            b.setObjectName("detailPrimary" if primary else "detailAction")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            if primary:
                self._actions_box.addWidget(b)
            else:
                secondary.append(b)
        rows = [secondary[i:i + 2] for i in range(0, len(secondary), 2)] or [[]]
        for i, buttons in enumerate(rows):
            last = i == len(rows) - 1
            if not buttons and not (last and more):
                continue
            host = QWidget()
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            for b in buttons:
                # marges internes plus etroites (feuille de style) ; la place
                # se partage selon la longueur des libelles
                b.PADDING = 16
                row.addWidget(b, b.fontMetrics().horizontalAdvance(b.full_text()) + b.PADDING)
            if last and more is not None:
                dots = QPushButton("⋯")
                dots.setObjectName("detailMore")
                dots.setCursor(Qt.PointingHandCursor)
                dots.setFixedWidth(32)
                dots.setToolTip(tr("Plus d'actions"))
                dots.setAccessibleName(tr("Plus d'actions"))
                dots.clicked.connect(
                    lambda _c=False, d=dots: more(d.mapToGlobal(d.rect().bottomLeft())))
                if not buttons:
                    row.addStretch(1)
                row.addWidget(dots)
            self._actions_box.addWidget(host)

    def show_content(self, cover: QPixmap, title: str, subtitle: str, rows, actions,
                     notice=None, genres=(), summary="", more=None):
        """rows : [(libelle, valeur)] ou [(libelle, valeur, (lien, fonction))]
        (valeurs vides ignorees) ;
        actions : [(libelle, fonction, principale)] ;
        more : fonction(position globale) du bouton « ⋯ » (menu de l'element) ;
        notice : (texte, libelle du bouton, fonction) d'un avertissement
        (recherche en echec), affiche apres les informations ;
        genres, summary : genres et resume de l'oeuvre (base en ligne)."""
        self.placeholder.hide()
        self._set_visible_content(True)
        self.set_cover(cover)
        self.title.setText(breakable(shorten(title)))
        self.title.setToolTip(plain(title) if len(title) > TITLE_MAX_CHARS else "")
        self.subtitle.setText(breakable(subtitle))
        self.subtitle.setVisible(bool(subtitle))
        self._set_genres(genres)
        self._set_summary(summary)
        for label, value, *link in rows:
            if not value:
                continue
            k = QLabel(label)
            k.setObjectName("detailKey")
            self.form.addRow(k, self._value_widget(value, link[0] if link else None))
        self._set_notice(notice)
        self._add_actions(actions, more)

    def _set_genres(self, genres):
        while self.genres.count():
            w = self.genres.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for genre in list(genres)[:6]:
            chip = QLabel(tr(genre))
            chip.setObjectName("detailGenre")
            chip.setTextFormat(Qt.PlainText)   # base en ligne : non fiable
            self.genres.addWidget(chip)
        self.genres_host.setVisible(bool(genres))

    def _set_summary(self, text):
        self._summary_full = text or ""
        self._summary_open = False
        self._show_summary()

    def _toggle_summary(self):
        self._summary_open = not self._summary_open
        self._show_summary()

    def _show_summary(self):
        text = self._summary_full
        long = len(text) > SUMMARY_PREVIEW
        if long and not self._summary_open:
            cut = text[:SUMMARY_PREVIEW].rsplit(" ", 1)[0].rstrip(" ,;:.")
            text = cut + "…"
        self.summary.setText(text)
        self.summary.setVisible(bool(text))
        self.summary_toggle.setVisible(long)
        self.summary_toggle.setText(tr("Réduire") if self._summary_open
                                    else tr("Lire tout le résumé"))

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
            #detailSummary {{ color: {c['text']}; font-size: 12px; }}
            #detailGenre {{
                color: {c['text']}; background: {c['button']}; border-radius: 9px;
                padding: 2px 8px; font-size: 11px;
            }}
            QPushButton#detailLink {{
                color: {theme.ACCENT}; background: transparent; border: none;
                padding: 0; font-size: 12px; text-align: left;
            }}
            QPushButton#detailLink:hover {{ text-decoration: underline; }}
            QPushButton#detailAction {{
                color: {c['text']}; background: {c['button']};
                border: 1px solid {c['border']}; border-radius: 8px;
                padding: 6px 6px; font-size: 12px;
            }}
            QPushButton#detailAction:hover {{ background: {c['button_hover']}; }}
            QPushButton#detailMore {{
                color: {c['text']}; background: {c['button']};
                border: 1px solid {c['border']}; border-radius: 8px;
                padding: 2px 0 5px 0; font-size: 18px; font-weight: 700;
            }}
            QPushButton#detailMore:hover {{ background: {c['button_hover']}; }}
            QPushButton:focus {{ border: 2px solid {c['text']}; }}
            {style.primary_button("QPushButton#detailPrimary",
                                  "border-radius: 8px; padding: 8px 14px; font-size: 13px;")}
            #detailNotice {{
                background: {c['warning_bg']}; border: 1px solid {c['warning_border']};
                border-radius: 8px;
            }}
            #detailNoticeText {{ color: {c['text']}; font-size: 12px; }}
            QPushButton#detailNoticeButton {{
                color: {c['text']}; background: {c['button']};
                border: 1px solid {c['text_dim']}; border-radius: 6px;
                padding: 5px 12px; font-size: 12px;
            }}
            QPushButton#detailNoticeButton:hover {{ background: {c['button_hover']}; }}
        """)
