"""Defilement de la bibliotheque : caches de rendu des cases et sondage des
cases visibles. Ces optimisations ne doivent rien changer a l'affichage."""

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from beheread.ui.library import delegates
from beheread.ui.library.constants import ROLE_PATH, ROLE_PROG_TEXT
from beheread.ui.library.delegates import MangaDelegate, _PixmapLRU
from beheread.ui.library.views import SmoothListWidget
from beheread.ui.library.widget import LibraryWidget


class _Covers:
    """CoverCache minimal : une couverture par chemin, sans arriere-plan."""

    def __init__(self):
        self.pixmaps = {}

    def lookup(self, path):
        return self.pixmaps.get(path)

    def error(self, _path):
        return None


def _pixmap(color, w=300, h=420):
    pm = QPixmap(w, h)
    pm.fill(QColor(color))
    return pm


def test_pixmap_lru_evicts_the_least_recently_used_beyond_budget(qapp):
    one = 10 * 10 * 4
    cache = _PixmapLRU(2 * one)
    cache.get("a", lambda: _pixmap("red", 10, 10))
    cache.get("b", lambda: _pixmap("red", 10, 10))
    cache.get("a", lambda: _pixmap("red", 10, 10))   # a redevient le plus recent
    cache.get("c", lambda: _pixmap("red", 10, 10))
    rendered = []
    cache.get("a", lambda: rendered.append("a") or _pixmap("red", 10, 10))
    cache.get("b", lambda: rendered.append("b") or _pixmap("red", 10, 10))
    assert rendered == ["b"]


def _grid(qtbot, store, covers, count=1):
    view = SmoothListWidget()
    qtbot.addWidget(view)
    view.setViewMode(QListWidget.IconMode)
    view.setGridSize(QSize(230, 380))
    view.setStyleSheet("QListWidget { background: #1b1e24; border: none; }")
    view.setItemDelegate(MangaDelegate(store, view, covers=covers))
    for i in range(count):
        item = QListWidgetItem(f"Tome {i}")
        item.setData(ROLE_PATH, f"/t{i}.cbz")
        view.addItem(item)
    view.resize(500, 420)
    view.show()
    qtbot.waitExposed(view)
    return view


def test_cached_cell_is_redrawn_when_its_data_changes(qtbot, store):
    """Le cache des cases ne doit jamais laisser une case perimee : texte de
    progression, selection et arrivee de la couverture changent l'image."""
    delegates._cells.clear()
    covers = _Covers()
    view = _grid(qtbot, store, covers)
    item = view.item(0)
    rect = view.visualItemRect(item)

    def shot():
        return view.viewport().grab(rect).toImage()

    before = shot()
    covers.pixmaps["/t0.cbz"] = _pixmap("#3b8e5b")
    view.viewport().update()
    with_cover = shot()
    assert with_cover != before

    item.setData(ROLE_PROG_TEXT, "12 / 40")
    assert shot() != with_cover

    progressed = shot()
    item.setSelected(True)
    assert shot() != progressed


def test_cell_cache_paints_the_same_image_as_a_direct_render(qtbot, store):
    """Une case recopiee depuis le cache est identique a son rendu direct."""
    covers = _Covers()
    covers.pixmaps["/t0.cbz"] = _pixmap("#8e3b46")
    view = _grid(qtbot, store, covers)
    item = view.item(0)
    item.setData(ROLE_PROG_TEXT, "3 / 10")
    rect = view.visualItemRect(item)
    delegates._cells.clear()
    first = view.viewport().grab(rect).toImage()     # rendu, mis en cache
    view.viewport().update()
    again = view.viewport().grab(rect).toImage()     # recopie du cache
    assert first == again


def test_rows_in_matches_a_full_scan(qtbot, store):
    """Le sondage par indexAt trouve exactement les cases qu'un parcours de
    toute la liste trouverait, lignes masquees (filtre) comprises."""
    view = _grid(qtbot, store, _Covers(), count=60)
    view.setGridSize(QSize(120, 150))
    view.setUniformItemSizes(True)
    view.setWrapping(True)
    view.setFlow(QListWidget.LeftToRight)
    view.setResizeMode(QListWidget.Adjust)
    for row in range(0, 60, 7):
        view.setRowHidden(row, True)
    view.resize(520, 400)
    qtbot.wait(350)   # QListView differe sa remise en page

    def full_scan(area):
        model = view.model()
        return [r for r in range(view.count())
                if not view.isRowHidden(r) and view.visualRect(model.index(r, 0)).intersects(area)]

    for position in (0, 230, 10_000):
        view.verticalScrollBar().setValue(position)
        area = view.viewport().rect()
        area = area.adjusted(0, -area.height() // 2, 0, area.height())
        assert LibraryWidget._rows_in(view, area) == full_scan(area)
