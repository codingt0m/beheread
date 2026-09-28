"""Bande horizontale « Continuer la lecture » en haut de la bibliotheque :
tomes en cours et tome suivant des series entamees (selection dans
library_model.continue_reading). Reutilise le rendu de la grille a echelle
reduite ; la molette y fait defiler horizontalement."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QLabel, QListWidget, QVBoxLayout, QWidget

from beheread.ui.library.constants import GRID_GAP, ROLE_PATH
from beheread.ui.library.delegates import MangaDelegate

SHELF_SCALE = 0.42


class _ShelfList(QListWidget):
    def wheelEvent(self, event):
        # molette verticale -> defilement horizontal (la bande n'a pas de
        # defilement vertical) ; un pave tactile horizontal garde le sien
        delta = event.angleDelta()
        if delta.x() == 0 and delta.y() != 0:
            sb = self.horizontalScrollBar()
            sb.setValue(sb.value() - delta.y())
            event.accept()
            return
        super().wheelEvent(event)


class ContinueShelf(QWidget):
    """Section titre + liste horizontale. Les items (QListWidgetItem portant
    les roles habituels ROLE_*) sont construits par la bibliotheque."""

    activated = Signal(str)                 # chemin du tome a ouvrir
    contextMenuRequested = Signal(str, object)   # chemin, position globale

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.setObjectName("shelf")
        # sans cet attribut, un QWidget simple ignore le « background » de sa
        # feuille de style : la bande prenait le fond de la fenetre et formait
        # un bloc de couleur differente de la grille
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 8, 20, 2)
        v.setSpacing(4)
        self.title = QLabel("Continuer la lecture")
        self.title.setObjectName("shelfTitle")
        v.addWidget(self.title)

        self.list = _ShelfList()
        self.list.setAccessibleName("Continuer la lecture")
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setFlow(QListWidget.LeftToRight)
        self.list.setWrapping(False)
        self.list.setMovement(QListWidget.Static)
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setSpacing(0)
        self.list.setWordWrap(True)
        self.delegate = MangaDelegate(store, self.list, compact=True)
        self.delegate.set_scale(SHELF_SCALE)
        self.list.setItemDelegate(self.delegate)
        self.list.setGridSize(QSize(self.delegate.cell_w + GRID_GAP,
                                    self.delegate.cell_h + GRID_GAP))
        # hauteur : une rangee de cases + la barre de defilement horizontale
        self.list.setFixedHeight(self.delegate.cell_h + GRID_GAP + 14)
        self.list.itemActivated.connect(
            lambda it: self.activated.emit(it.data(ROLE_PATH)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        v.addWidget(self.list)

    def _on_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is not None:
            self.contextMenuRequested.emit(item.data(ROLE_PATH),
                                           self.list.viewport().mapToGlobal(pos))

    def apply_colors(self, c, accent):
        self.setStyleSheet(f"""
            #shelf {{ background: {c['list_bg']}; }}
            #shelfTitle {{
                color: {c['text']}; font-size: 15px; font-weight: 700;
            }}
            QListWidget {{ background: {c['list_bg']}; border: none; }}
        """)
        self.list.viewport().update()
