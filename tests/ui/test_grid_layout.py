"""Stabilite de la grille centree (SmoothListWidget)."""

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyle

from beheread.ui.library.views import SmoothListWidget

GRID = QSize(120, 150)
COLS = 5


def _grid(qtbot, count):
    view = SmoothListWidget()
    qtbot.addWidget(view)
    view.setViewMode(QListWidget.IconMode)
    view.setFlow(QListWidget.LeftToRight)
    view.setWrapping(True)
    view.setResizeMode(QListWidget.Adjust)
    view.setMovement(QListWidget.Static)
    view.setUniformItemSizes(True)
    view.setSpacing(0)
    view.setGridSize(GRID)
    for i in range(count):
        item = QListWidgetItem(str(i))
        item.setSizeHint(GRID)
        view.addItem(item)
    return view


def _columns(view):
    return len({view.visualItemRect(view.item(i)).x() for i in range(view.count())})


# decalages (px) autour de COLS colonnes : de part et d'autre du seuil, et dans
# la zone ou la largeur de la barre de defilement decide du nombre de colonnes
@pytest.mark.parametrize("offset", [-3, 2, 9, 16, 21, 40])
def test_grid_does_not_oscillate_when_the_scrollbar_decides_the_columns(qtbot, offset):
    """Tomes qui tiennent sur deux rangees a COLS colonnes mais pas a COLS - 1 :
    la vue ne doit pas alterner sans fin entre « barre de defilement, donc une
    colonne de moins » et « plus de barre, donc une colonne de plus » (les
    couvertures clignotaient a l'entree dans un dossier de serie)."""
    view = _grid(qtbot, 2 * COLS - 1)
    bar = view.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, view.verticalScrollBar())
    frame = 2 * view.frameWidth()
    view.resize(COLS * GRID.width() + bar + frame + offset, int(2.5 * GRID.height()))
    view.show()
    qtbot.waitExposed(view)
    qtbot.wait(350)   # QListView differe sa remise en page de 100 ms

    changes = []
    view.verticalScrollBar().rangeChanged.connect(lambda lo, hi: changes.append((lo, hi)))
    margins, columns = view.viewportMargins(), _columns(view)
    qtbot.wait(450)
    assert changes == []
    assert view.viewportMargins() == margins and _columns(view) == columns
    # centree dans la zone visible. La somme des marges est imposee par le
    # nombre de colonnes : quand il reste moins que la place de la barre a
    # repartir, l'ecart au centre peut atteindre une demi-barre.
    assert columns == COLS if offset >= 2 else COLS - 1
    used = columns * GRID.width()
    left = view.viewportMargins().left()
    visible = view.viewport().width() + margins.left() + margins.right()
    assert abs(left - (visible - used) / 2) <= bar / 2 + 1, (left, visible, used)
