"""Tests d'interface des statistiques d'une serie (pytest-qt)."""

import datetime as dt

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLabel

from beheread.core import series_stats as ss
from beheread.core import units
from beheread.infra import virtual
from beheread.ui.library import virtual_ui
from beheread.ui.stats_view import StatsDialog
from tests.ui.conftest import make_cbz, scanned
from tests.ui.test_stats_ui import LIBRARY, TODAY, _read
from tests.ui.test_virtual_ui import _library, _number_dialog


def _setup(store, mangas):
    b1 = _read(store, mangas, "Berserk - Tome 1", 3, 40, 1200, finished=True, seed=1)
    b2 = _read(store, mangas, "Berserk - Tome 2", 1, 20, 600, seed=2)
    p1 = _read(store, mangas, "Pluto - Tome 1", 2, 10, 300, seed=3)
    k1, k2, kp = (store.key_for(p) for p in (b1, b2, p1))
    resolve = {k1: ("berserk", "Berserk"), k2: ("berserk", "Berserk"), kp: ("pluto", "Pluto")}
    holdings = ss.SeriesHoldings("berserk", "Berserk", "Kentaro Miura", (
        ss.SeriesItem(1, units.VOLUME, k1, ss.FINISHED, 39, 40),
        ss.SeriesItem(2, units.VOLUME, k2, ss.READING, 19, 80),
        ss.SeriesItem(3, units.VOLUME, "k3", ss.UNREAD, 0, 0)))
    return resolve, {"berserk": holdings}.get


def _texts(widget):
    return [lab.text() for lab in widget.findChildren(QLabel)]


def test_ranking_opens_the_series_and_comes_back(store, qtbot, mangas):
    resolve, holdings = _setup(store, mangas)
    opened = []
    dlg = StatsDialog(store, LIBRARY, "dark", today=TODAY, resolve=resolve.get,
                      holdings=holdings, open_series=opened.append)
    qtbot.addWidget(dlg)
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
        "Temps passé : 30 min - 60 pages · 2 jours de lecture",
        "Un tome vous prend : 20 min - Tome 1",
        # 1800 s pour 60 pages ; Pluto au meme rythme (300 s, 10 pages)
        "Vitesse : 2 pages / min - comme votre moyenne",
        # 61 pages du tome 2 a 30 s ; 900 s par jour de lecture
        "Reste à lire : ≈ 30 min - 2 tomes · environ 2 jours de lecture à votre rythme"]
    assert view.tiles[2].toolTip() == "30 s par page"
    assert view.tiles[3].toolTip() == "Hors 1 titre au nombre de pages inconnu."
    # aucune notion de possession : le parcours de lecture seulement
    assert [(i[0], i[1]) for i in view.shelf.items] == [("1", "here"), ("2", "reading"),
                                                        ("3", "unread")]
    assert view.shelf.items[1][2] == 19 / 80
    assert [t for t, _s in view.shelf.legend] == ["1 lu dans le lecteur", "1 en cours", "1 à lire"]
    assert view.shelf_sum.text() == "1 / 3 tomes lus"
    assert [b[1] for b in view.bars.bars] == [1200]
    assert view.bars.notes[0][:2] == ("s / page", ["30,0"])
    journal = _texts(view.journal)
    assert journal[:2] == ["sam. 26 sept.", "10 min"] and "Tome 2 commencé" in journal[2]
    assert "Tome 1 terminé" in journal[5]

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
    holdings = ss.SeriesHoldings("x", "Neuve", "", (
        ss.SeriesItem(1, units.VOLUME, "a", ss.UNREAD, 0, 100),
        ss.SeriesItem(2, units.VOLUME, "b", ss.UNREAD, 0, 100)))
    store.reading_pace = lambda: 10.0
    dlg = StatsDialog(store, LIBRARY, "dark", today=TODAY, holdings={"x": holdings}.get, series="x")
    qtbot.addWidget(dlg)
    view = dlg.series_view
    assert dlg.series_key == "x" and dlg.caption.text() == "pas encore lue dans le lecteur"
    assert view.tiles[3].accessibleName() == "Reste à lire : ≈ 33 min - 2 tomes"
    assert view.bars.bars == []
    assert any("vos jours de lecture apparaîtront ici" in t for t in _texts(view.journal))
    assert any("Ouvrez un tome de la série" in t for t in _texts(view.facts))


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
    # pas de tome manquant : seule la lecture compte
    assert [(i.number, i.status) for i in h.items] == [(1, "finished"), (3, "unread")]
    assert lib._stats_holdings("inconnue") is None
    # le panneau d'informations de la serie donne le temps passe
    assert lib._series_seconds(key) == 120

    opened = []
    monkeypatch.setattr(StatsDialog, "exec", lambda self: opened.append(self))
    lib.open_series_stats(key)
    dlg = opened[0]
    assert dlg.series_key == key and dlg.series_view.report.finished == 1
    # le classement de la vue generale ouvre la meme serie
    dlg.show_overview()
    dlg.set_period("all")
    assert dlg.series_list.clickable == {0}


def test_virtual_volume_is_a_volume_and_hides_its_chapters(window, qtbot, mangas, store,
                                                           monkeypatch):
    lib, paths = _library(window, qtbot, mangas, store,
                          ["Serie T01", "Serie T02"] + [f"Serie Chapitre {n}" for n in range(21, 26)])
    ch21 = paths["Serie · Chapitre 21"]
    # chapitre lu avant d'etre regroupe : son temps passe au tome virtuel
    store.record_reading(ch21, 30, 300, True, "Serie Chapitre 21", "Serie", date=dt.date.today())
    monkeypatch.setattr(virtual_ui, "VirtualVolumeDialog", _number_dialog(3))
    lib._group_chapters([ch21, paths["Serie · Chapitre 22"], paths["Serie · Chapitre 23"]])
    assert any(virtual.is_virtual(e.path) for e in lib._entries)

    h = lib._stats_holdings("serie")
    assert [(i.number, i.unit) for i in h.items] == [
        (1, units.VOLUME), (2, units.VOLUME), (3, units.VOLUME),
        (24, units.CHAPTER), (25, units.CHAPTER)]
    assert h.items[2].covers == (21, 22, 23) and store.key_for(ch21) in h.items[2].aliases
    report = ss.build_series_report(store.reading_log, h, dt.date.today())
    assert [v.seconds for v in report.volumes if v.item.number == 3] == [300]
