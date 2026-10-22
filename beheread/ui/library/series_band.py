"""Bandeau d'un dossier de serie ouvert, au-dessus de ses tomes : nom,
auteur, tomes possedes sur tomes parus et chapitres qui les completent."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from beheread.i18n import tr, trn
from beheread.ui import theme


class SeriesBand(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("seriesBand")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 14, 24, 6)
        v.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(16)
        names = QVBoxLayout()
        names.setSpacing(4)
        # noms de serie et d'auteur : sources non fiables, texte brut
        self.name = QLabel()
        self.name.setObjectName("bandName")
        self.name.setTextFormat(Qt.PlainText)
        self.sub = QLabel()
        self.sub.setObjectName("bandSub")
        self.sub.setTextFormat(Qt.PlainText)
        names.addWidget(self.name)
        names.addWidget(self.sub)
        top.addLayout(names, 1)
        self.bar = QProgressBar()
        self.bar.setObjectName("bandBar")
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(220, 8)
        self.bar.setAccessibleName(tr("Tomes possédés"))
        top.addWidget(self.bar, 0, Qt.AlignVCenter)
        self.count = QLabel()
        self.count.setObjectName("bandCount")
        self.count.setTextFormat(Qt.RichText)   # nombres seulement
        top.addWidget(self.count, 0, Qt.AlignVCenter)
        v.addLayout(top)


    def set_content(self, name, subtitle, owned, published, chapters=0, chapter_range=""):
        """`chapters` : nombre de chapitres de la serie ; `chapter_range`
        (« ch. 211 a 232 ») : ceux qui completent les tomes d'une serie mixte,
        vide pour une serie faite de chapitres seuls. Les tomes et chapitres
        manquants se voient dans la grille (cases « Non possede », voir les
        preferences)."""
        self.name.setText(name)
        self.sub.setText(subtitle)
        self.sub.setVisible(bool(subtitle))
        if published:
            self.bar.setRange(0, published)
            self.bar.setValue(min(owned, published))
            self.bar.show()
            count = trn(owned, "<b>{n}</b> possédé sur {published}",
                        "<b>{n}</b> possédés sur {published}", published=published)
        else:
            self.bar.hide()
            count = (trn(owned, "<b>{n}</b> tome", "<b>{n}</b> tomes") if owned or not chapters
                     else trn(chapters, "<b>{n}</b> chapitre", "<b>{n}</b> chapitres"))
        if chapter_range:
            count += " · + <b>" + chapter_range + "</b>"
        self.count.setText(count)

    def apply_colors(self, c):
        self.setStyleSheet(f"""
            #seriesBand {{ background: {c['list_bg']}; }}
            #bandName {{ color: {c['text']}; font-size: 18px; font-weight: 700; }}
            #bandSub, #bandCount {{ color: {c['text_dim']}; font-size: 13px; }}
            #bandCount b {{ color: {c['text']}; }}
            QProgressBar#bandBar {{ background: {c['button']}; border: none; border-radius: 4px; }}
            QProgressBar#bandBar::chunk {{ background: {theme.FINISHED}; border-radius: 4px; }}
        """)
