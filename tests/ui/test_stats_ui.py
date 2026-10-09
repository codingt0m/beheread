"""Tests d'interface de l'ecran de statistiques (pytest-qt)."""

import datetime as dt

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea

from beheread.ui.stats_view import StatsDialog
from tests.ui.conftest import make_cbz, scanned

TODAY = dt.date(2026, 9, 27)
LIBRARY = {"unread": 3, "reading": 1, "finished": 2, "remaining_pages": 600, "unknown_pages": 1}


def _read(store, mangas, name, offset, pages, seconds, finished=False, seed=0):
    path = make_cbz(mangas, name, seed=seed)
    store.record_reading(path, pages, seconds, finished, name, name.split(" - ")[0],
                         date=TODAY - dt.timedelta(days=offset))
    return path


def _dialog(store, qtbot, size=(1440, 900), **kwargs):
    """Ecran de statistiques aux dimensions d'un ecran donne (hors ecran)."""
    dlg = StatsDialog(store, LIBRARY, "dark", today=TODAY, **kwargs)
    qtbot.addWidget(dlg)
    dlg.resize(*size)
    dlg.fit_height()
    return dlg


def _tiles(dlg):
    return [t.accessibleName() for t in dlg.tiles]


def _texts(dlg):
    return " | ".join(lab.text() for lab in dlg.findChildren(QLabel) if not lab.isHidden())


def _titles(dlg):
    return [title for title, _date, _count in dlg.finished_list.items]


def test_every_figure_follows_the_chosen_period(store, qtbot, mangas):
    _read(store, mangas, "Berserk - Tome 1", 0, 40, 1200, finished=True, seed=1)
    _read(store, mangas, "Berserk - Tome 2", 1, 20, 600, seed=2)
    _read(store, mangas, "Pluto - Tome 1", 20, 60, 1800, seed=3)
    _read(store, mangas, "Pluto - Tome 2", 45, 30, 1500, finished=True, seed=4)

    dlg = _dialog(store, qtbot)
    assert dlg.report.period.key == "30d" and dlg.period_buttons["30d"].isChecked()
    # la periode comparee est nommee une fois ; les tuiles ne portent que l'ecart
    assert dlg.caption.text() == "29 août – 27 sept. 2026 · comparé aux 30 jours précédents"
    assert _tiles(dlg) == [
        "Temps de lecture : 1 h 00 - ▲ 35 min - 20 min par jour de lecture · 3 séances",
        "Pages lues : 120 - ▲ 90 - dans 3 tomes",
        "Tomes terminés : 1 - = identique",
        "Jours de lecture : 3 sur 30 - ▲ 2"]
    assert dlg.tiles[0].toolTip() == ("35 min de plus que les 30 jours précédents (25 min).")
    assert dlg.days_meter.ratio == 0.1
    assert dlg.pages_spark.values[-1] == 40 and len(dlg.pages_spark.values) == 30
    assert len(dlg.time_chart.bars) == 30 and dlg.time_chart.bars[-1][1] == 1200
    # infobulle : la valeur d'abord, puis ce qui la situe
    assert dlg.time_chart.bars[-1][2] == "20 min\n27/09 · 40 pages · 1 tome terminé"
    assert dlg.time_card.title.text() == "Temps de lecture par jour"
    assert dlg.time_card.table.rowCount() == 30
    assert dlg.time_card.table.item(0, 1).text() == "20 min"
    assert [r[0] for r in dlg.series_list.rows] == ["Berserk", "Pluto"]
    assert dlg.finished_list.items == [("Berserk - Tome 1", "27 sept.", 1)]
    assert dlg.calendar_card.subtitle.text() == "Série en cours : 2 jours"

    # 7 jours : chaque composant est mis a jour en place (memes objets)
    chart, tile = dlg.time_chart, dlg.tiles[1]
    dlg.period_buttons["7d"].click()
    assert dlg.report.period.key == "7d" and store.ui_pref("stats_period") == "7d"
    assert dlg.time_chart is chart and dlg.tiles[1] is tile
    assert _tiles(dlg)[1] == "Pages lues : 60 - ▲ 60 - dans 2 tomes"
    assert len(chart.bars) == 7 and len(dlg.calendar.days) == 7
    assert [r[0] for r in dlg.series_list.rows] == ["Berserk"]

    dlg.period_buttons["all"].click()
    assert _tiles(dlg)[2] == "Tomes terminés : 2"            # « Tout » : rien a comparer
    assert dlg.caption.text() == "13 août – 27 sept. 2026"
    assert _titles(dlg) == ["Berserk - Tome 1", "Pluto - Tome 2"]
    dlg.period_buttons["12m"].click()
    assert len(chart.bars) == 12 and dlg.time_card.title.text() == "Temps de lecture par mois"
    assert dlg.caption.text().endswith("historique trop court pour comparer")
    assert _tiles(dlg)[0].startswith("Temps de lecture : 1 h 25 - 21 min par jour")
    assert len(dlg.calendar.days) == 362 and not dlg.calendar.monthly

    # le choix de periode est retenu pour la prochaine ouverture
    assert _dialog(store, qtbot).report.period.key == "12m"


def test_calendar_shades_days_by_reading_time(store, qtbot, mangas):
    _read(store, mangas, "Berserk - Tome 1", 0, 40, 2400, seed=1)
    _read(store, mangas, "Berserk - Tome 2", 2, 10, 300, finished=True, seed=2)
    cal = _dialog(store, qtbot).calendar
    assert cal.monthly and len(cal.days) == 30 and len(cal.weeks) == 5
    levels = [cal.level(b) for b in cal.days]
    assert levels[-1] == 4 and levels[-3] == 2 and levels[-2] == 0 and sum(levels) == 6
    assert cal.tip(29) == "40 min\ndim. 27/09/2026 · 40 pages"
    assert cal.tip(27) == "5 min\nven. 25/09/2026 · 10 pages · 1 tome terminé"
    assert cal.tip(28) == "Pas de lecture\nsam. 26/09/2026"
    # au clavier : meme parcours qu'a la souris, un jour ou une semaine a la fois
    for key, expected in ((Qt.Key_Left, 29), (Qt.Key_Left, 28), (Qt.Key_Up, 21), (Qt.Key_Right, 22)):
        QApplication.sendEvent(cal, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
        assert cal.hover == expected


def test_screen_is_fullscreen_and_never_scrolls(store, qtbot, mangas):
    """Plein ecran, tout sur un ecran : pas de zone de defilement, et ce qui
    ne tient pas en hauteur est retire plutot que de deborder."""
    for i in range(6):     # six contenus distincts (make_cbz) ; deux fins de tome par jour
        path = _read(store, mangas, f"Serie {i} - Tome 1", i, 30, 600 + 60 * i,
                     finished=True, seed=i)
        store.record_reading(path, 0, 0, True, f"Serie {i} - Tome 1", f"Serie {i}",
                             date=TODAY - dt.timedelta(days=10 + i))
    opened = StatsDialog(store, LIBRARY, "dark", today=TODAY)
    qtbot.addWidget(opened)
    assert opened.windowState() & Qt.WindowFullScreen        # tel qu'il s'ouvre
    dlg = _dialog(store, qtbot, size=(1440, 900))
    assert dlg.findChildren(QScrollArea) == []
    assert not dlg.close_button.isHidden()                   # pas de barre de titre en plein ecran

    # ecran haut : les deux rangees, et le contenu tient dans la hauteur
    assert not dlg.habits.isHidden()
    assert dlg.root.minimumSize().height() <= 900
    # les listes ne dessinent que les lignes qui tiennent, et le disent
    dlg.finished_list.resize(300, 5 * dlg.finished_list.ROW)
    shown, more = dlg.finished_list.visible_items()
    assert len(shown) == 4 and more == 8 and dlg.finished_list.total == 12
    dlg.finished_list.resize(300, 12 * dlg.finished_list.ROW)
    assert dlg.finished_list.visible_items() == (dlg.finished_list.items, 0)
    dlg.series_list.resize(300, 4 * dlg.series_list.ROW)
    assert len(dlg.series_list.rows) == 6 and len(dlg.series_list.visible_rows()) == 4

    # ecran bas : la seconde rangee est retiree, et ce qui reste tient
    dlg.resize(1100, 600)
    dlg.fit_height()
    assert dlg.habits.isHidden() and not dlg.detail.isHidden() and not dlg.tiles_host.isHidden()
    assert dlg.root.minimumSize().height() <= 600
    # elle revient quand la place revient, et reste retiree en changeant de periode
    dlg.period_buttons["7d"].click()
    assert dlg.habits.isHidden()
    dlg.resize(1440, 900)
    dlg.fit_height()
    assert not dlg.habits.isHidden()

    dlg.close_button.click()
    assert dlg.result() == StatsDialog.Accepted


def test_empty_journal_shows_a_single_message(store, qtbot):
    dlg = _dialog(store, qtbot)
    assert not dlg.empty_card.isHidden()
    assert all(w.isHidden() for w in (dlg.tiles_host, dlg.detail, dlg.calendar_card,
                                      dlg.finished_card))
    assert "Aucune lecture enregistrée pour l'instant" in _texts(dlg)
    # l'etat de la bibliotheque reste affiche ; sans rythme mesure, pas de faux chiffre
    assert not dlg.habits.isHidden() and not dlg.library_card.isHidden()
    assert "Rythme de lecture pas encore mesuré" in _texts(dlg)
    assert dlg.backlog_value.isHidden()

    store.update_page_seconds(12.0)
    dlg = _dialog(store, qtbot)
    assert dlg.backlog_value.text() == "≈ 2 h"
    assert dlg.backlog_detail.text() == ("600 pages à votre rythme de 12 s par page, "
                                         "hors 1 tome au nombre de pages inconnu.")
    assert dlg.library_card.subtitle.text() == "6 tomes · indépendant de la période"


def test_series_and_titles_follow_the_library(store, qtbot, mangas):
    a = _read(store, mangas, "Ancien - Tome 1", 0, 10, 600, finished=True, seed=1)
    b = _read(store, mangas, "Nouveau - Tome 2", 1, 10, 300, seed=2)
    names = {store.key_for(a): ("serie", "Nom actuel"), store.key_for(b): ("serie", "Nom actuel")}
    dlg = _dialog(store, qtbot, resolve=names.get, titles={store.key_for(a): "Titre actuel"})
    assert dlg.series_list.rows == [("Nom actuel", 900.0, "15 min · 100 %")]
    assert dlg.finished_list.items == [("Titre actuel", "27 sept.", 1)]


def test_finished_volumes_without_a_title_share_one_line(store, qtbot):
    """Tomes termines avant le journal dont le fichier a disparu : leur titre
    est perdu. Une ligne par jour, pas une ligne identique par tome."""
    day = TODAY - dt.timedelta(days=3)
    for volume in ("c1:a", "c1:b", "c1:c", "C:\\Mangas\\Vagabond - Tome 3.cbz"):
        store.reading_log.add("pc", "PC", day, volume, 0, 0, True, "", "", 1.0)
    store.reading_log.add("pc", "PC", TODAY, "c1:d", 30, 28, True, "Pluto - Tome 1", "Pluto", 2.0)
    dlg = _dialog(store, qtbot)
    assert dlg.finished_list.items == [
        ("Pluto - Tome 1", "27 sept.", 1),
        ("Vagabond - Tome 3", "24 sept.", 1),
        ("3 tomes absents de la bibliothèque", "24 sept.", 3)]
    assert dlg.finished_list.total == dlg.report.totals.finished == 5
    dlg.finished_list.resize(300, 6 * dlg.finished_list.ROW)
    assert dlg.finished_list.visible_items()[1] == 0         # tout est liste : rien « en plus »
    assert dlg.series_list.rows == [("Pluto", 28.0, "28 s · 100 %")]


def test_method_is_a_tooltip_and_takes_no_room(store, qtbot):
    dlg = _dialog(store, qtbot)
    assert "Marquer comme lu" in dlg.method.toolTip() and "1 s" in dlg.method.toolTip()
    dlg.method.click()                                       # au clic comme au survol
    assert not dlg.method.isCheckable()


def test_stats_open_from_the_library(window, qtbot, mangas, store, monkeypatch):
    path = make_cbz(mangas, "Alpha - Tome 1", pages=6, seed=1)
    make_cbz(mangas, "Alpha - Tome 2", pages=4, seed=2)
    store.add_folder(str(mangas))
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 2)
    store.set_progress(path, 3, 6, False)
    store.set_page_count(str(mangas / "Alpha - Tome 2.cbz"), 4)
    store.record_reading(path, 2, 60, True, "ancien titre", "alpha (ancien nom)")
    lib._rebuild_list()

    opened = []
    monkeypatch.setattr(StatsDialog, "exec", lambda self: opened.append(self))
    lib.open_stats()
    dlg = opened[0]
    assert dlg.windowState() & Qt.WindowFullScreen
    assert {k: dlg.library[k] for k in ("unread", "reading", "finished")} == {
        "unread": 1, "reading": 1, "finished": 0}
    assert dlg.library["remaining_pages"] == 3 + 4 and dlg.library["unknown_pages"] == 0
    # serie et tome nommes comme dans la bibliotheque, pas comme au moment de la lecture
    dlg.set_period("all")
    assert [r[0] for r in dlg.series_list.rows] == ["Alpha"]
    assert _titles(dlg) == ["Alpha · Tome 1"]
