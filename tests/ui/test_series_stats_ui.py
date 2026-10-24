"""Tests d'interface des statistiques d'une serie (pytest-qt)."""

import datetime as dt

from PySide6.QtCore import QPoint, Qt

from beheread.core import series_stats as ss
from beheread.core import units
from beheread.ui.stats_view import StatsDialog
from tests.ui.conftest import make_cbz, scanned
from tests.ui.test_stats_ui import LIBRARY, TODAY, _read


def _setup(store, mangas):
    b1 = _read(store, mangas, "Berserk - Tome 1", 3, 40, 1200, finished=True, seed=1)
    b2 = _read(store, mangas, "Berserk - Tome 2", 1, 20, 600, seed=2)
    p1 = _read(store, mangas, "Pluto - Tome 1", 2, 10, 300, seed=3)
    k1, k2, kp = (store.key_for(p) for p in (b1, b2, p1))
    resolve = {k1: ("berserk", "Berserk"), k2: ("berserk", "Berserk"), kp: ("pluto", "Pluto")}
    holdings = ss.SeriesHoldings("berserk", "Berserk", "Kentaro Miura", 4, (
        ss.SeriesItem(1, units.VOLUME, k1, ss.FINISHED, 39, 40),
        ss.SeriesItem(2, units.VOLUME, k2, ss.READING, 19, 80),
        ss.SeriesItem(3, units.VOLUME, "k3", ss.UNREAD, 0, 0),
        ss.SeriesItem(4, units.VOLUME, None, ss.MISSING)))
    return resolve, {"berserk": holdings}.get


def test_ranking_opens_the_series_and_comes_back(store, qtbot, mangas):
    resolve, holdings = _setup(store, mangas)
    opened = []
    dlg = StatsDialog(store, LIBRARY, "dark", today=TODAY, resolve=resolve.get,
                      holdings=holdings, open_series=opened.append)
    qtbot.addWidget(dlg)
    dlg.setWindowState(Qt.WindowNoState)
    dlg.resize(1440, 900)
    dlg.show()
    qtbot.waitExposed(dlg)
    # seule une serie de la bibliotheque s'ouvre ; la carte le dit
    assert [r[0] for r in dlg.series_list.rows] == ["Berserk", "Pluto"]
    assert dlg.series_list.clickable == {0}
    assert dlg.series_card.subtitle.text() == "Part du temps de lecture · cliquez pour le détail"
    qtbot.mouseClick(dlg.series_list, Qt.LeftButton, pos=QPoint(20, 10 + dlg.series_list.ROW))
    assert dlg.series_key is None                            # Pluto : rien
    qtbot.mouseClick(dlg.series_list, Qt.LeftButton, pos=QPoint(20, 10))

    assert dlg.series_key == "berserk" and dlg.pages.currentIndex() == 1
    assert dlg.title.text() == "Berserk" and dlg.crumb.isVisible()
    assert not dlg.segmented.isVisible() and dlg.open_button.isVisible()
    assert dlg.caption.text() == "Kentaro Miura · lue du 24 sept. 2026 au 26 sept. 2026"
    view = dlg.series_view
    assert [t.accessibleName() for t in view.tiles] == [
        "Temps passé dans la série : 30 min - 60 pages · 2 séances",
        "Tomes lus : 1 sur 3 - 33 % · 4 tomes parus",
        # 1800 s pour 60 pages ; Pluto au meme rythme (300 s, 10 pages)
        "Rythme : 30 s par page - comme votre moyenne",
        # 61 pages du tome 2 a 30 s ; 2 tomes au rythme d'une fin en 90 jours
        "Reste à lire : ≈ 30 min - 2 tomes au rythme de la série\nFin estimée : mars 2027"]
    assert view.tiles[3].toolTip() == ("Fin estimée d'après 1 fin de lecture dans les 90 "
                                       "derniers jours.\nHors 1 titre au nombre de pages inconnu.")
    assert [(i[0], i[1]) for i in view.shelf.items] == [
        ("1", "finished"), ("2", "reading"), ("3", "unread"), ("4", "missing")]
    assert view.shelf.items[1][2] == 19 / 80
    assert [t for t, _s in view.shelf.legend] == ["1 terminé", "1 en cours", "1 non lu",
                                                  "1 non possédé"]
    assert [p[1] for p in view.progress.points] == [1]
    assert view.progress.projection[1] == 3                  # 1 lu + 2 restants
    assert [b[1] for b in view.bars.bars] == [1200]

    # Echap ramene a la vue generale, sans fermer la fenetre
    dlg.reject()
    assert dlg.series_key is None and dlg.isVisible() and dlg.title.text() == "Statistiques de lecture"
    assert dlg.segmented.isVisible() and not dlg.open_button.isVisible()
    # au clavier : fleche puis Entree
    qtbot.keyClick(dlg.series_list, Qt.Key_Down)
    qtbot.keyClick(dlg.series_list, Qt.Key_Return)
    assert dlg.series_key == "berserk"
    dlg.open_button.click()
    assert dlg.result() == StatsDialog.Accepted and opened == ["berserk"]


def test_series_never_read_has_a_clear_empty_state(store, qtbot):
    holdings = ss.SeriesHoldings("x", "Neuve", "", None, (
        ss.SeriesItem(1, units.VOLUME, "a", ss.UNREAD, 0, 100),
        ss.SeriesItem(2, units.VOLUME, "b", ss.UNREAD, 0, 100)))
    store.reading_pace = lambda: 10.0
    dlg = StatsDialog(store, LIBRARY, "dark", today=TODAY, holdings={"x": holdings}.get, series="x")
    qtbot.addWidget(dlg)
    view = dlg.series_view
    assert dlg.series_key == "x" and dlg.caption.text() == "pas encore lue dans le lecteur"
    assert view.tiles[3].accessibleName() == "Reste à lire : ≈ 33 min - 2 tomes"
    assert view.progress.points == [] and view.bars.bars == []
    assert "Ouvrez un tome de la série" in view.facts.findChildren(type(dlg.title))[1].text()


def test_series_stats_open_from_the_library(window, qtbot, mangas, store, monkeypatch):
    p1 = make_cbz(mangas, "Alpha - Tome 1", pages=6, seed=1)
    make_cbz(mangas, "Alpha - Tome 3", pages=4, seed=2)
    store.add_folder(str(mangas))
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 2)
    store.set_progress(p1, 5, 6, True)
    store.record_reading(p1, 6, 120, True, "Alpha - Tome 1", "Alpha", date=dt.date.today())
    lib._rebuild_list()
    key = lib._info[p1].series_key

    h = lib._stats_holdings(key)
    assert h.name == "Alpha"
    assert [(i.number, i.status, i.volume is not None) for i in h.items] == [
        (1, "finished", True), (2, "missing", False), (3, "unread", True)]
    assert lib._stats_holdings("inconnue") is None

    opened = []
    monkeypatch.setattr(StatsDialog, "exec", lambda self: opened.append(self))
    lib.open_series_stats(key)
    dlg = opened[0]
    assert dlg.series_key == key and dlg.series_view.report.finished == 1
    # le classement de la vue generale ouvre la meme serie
    dlg.show_overview()
    dlg.set_period("all")
    assert dlg.series_list.clickable == {0}
