"""Bandeau d'un dossier de serie ouvert, au-dessus de ses tomes : nom,
auteur, tomes possedes sur tomes parus et tomes manquants, avec le choix de
les montrer dans la grille."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from beheread.ui import theme


class SeriesBand(QWidget):
    showMissingToggled = Signal(bool)

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
        self.bar.setAccessibleName("Tomes possédés")
        top.addWidget(self.bar, 0, Qt.AlignVCenter)
        self.count = QLabel()
        self.count.setObjectName("bandCount")
        self.count.setTextFormat(Qt.RichText)   # nombres seulement
        top.addWidget(self.count, 0, Qt.AlignVCenter)
        v.addLayout(top)

        self.note = QFrame()
        self.note.setObjectName("bandNote")
        nh = QHBoxLayout(self.note)
        nh.setContentsMargins(14, 8, 14, 8)
        nh.setSpacing(10)
        self.missing = QLabel()
        self.missing.setObjectName("bandMissing")
        self.missing.setTextFormat(Qt.RichText)   # seuls des numeros (voir set_content)
        self.missing.setWordWrap(True)
        nh.addWidget(self.missing, 1)
        self.show_missing = QCheckBox("Afficher les tomes manquants dans la grille")
        self.show_missing.toggled.connect(self.showMissingToggled.emit)
        nh.addWidget(self.show_missing)
        v.addWidget(self.note)

    def set_content(self, name, subtitle, owned, published, missing_text, missing_count,
                    show_missing):
        """`missing_text` : numeros manquants deja mis en forme (« 6, 12,
        29 a 36 ») - uniquement des chiffres, d'ou le texte enrichi sans
        risque pour le gras."""
        self.name.setText(name)
        self.sub.setText(subtitle)
        self.sub.setVisible(bool(subtitle))
        if published:
            self.bar.setRange(0, published)
            self.bar.setValue(min(owned, published))
            self.bar.show()
            self.count.setText(f"<b>{owned}</b> possédé{'s' if owned > 1 else ''} sur {published}")
        else:
            self.bar.hide()
            self.count.setText(f"<b>{owned}</b> tome{'s' if owned > 1 else ''}")
        self.note.setVisible(missing_count > 0)
        if missing_count:
            word = "tome" if missing_count == 1 else "tomes"
            self.missing.setText(f"Il vous manque {missing_count} {word} : <b>{missing_text}</b>.")
        self.show_missing.blockSignals(True)
        self.show_missing.setChecked(show_missing)
        self.show_missing.blockSignals(False)

    def apply_colors(self, c):
        self.setStyleSheet(f"""
            #seriesBand {{ background: {c['list_bg']}; }}
            #bandName {{ color: {c['text']}; font-size: 18px; font-weight: 700; }}
            #bandSub, #bandCount {{ color: {c['text_dim']}; font-size: 13px; }}
            #bandCount b {{ color: {c['text']}; }}
            #bandNote {{ background: {c['panel']}; border: 1px solid {c['border']};
                         border-radius: 8px; }}
            #bandMissing {{ color: {c['text']}; font-size: 13px; }}
            QCheckBox {{ color: {c['text_dim']}; }}
            QProgressBar#bandBar {{ background: {c['button']}; border: none; border-radius: 4px; }}
            QProgressBar#bandBar::chunk {{ background: {theme.FINISHED}; border-radius: 4px; }}
        """)
