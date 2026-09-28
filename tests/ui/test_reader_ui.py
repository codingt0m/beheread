"""Tests d'interface du lecteur (pytest-qt)."""

import time

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from tests.ui.conftest import make_cbz, make_pdf


def _open(window, qtbot, path):
    window.open_manga(path)
    reader = window.reader
    qtbot.waitUntil(lambda: 0 in reader.cache and not reader.cache[0].isNull(), timeout=10000)
    return reader


def _wheel(reader, dy, pixel=False):
    ev = QWheelEvent(QPointF(400, 300), QPointF(400, 300),
                     QPoint(0, dy) if pixel else QPoint(0, 0), QPoint(0, 0 if pixel else dy),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(reader, ev)
    reader.repaint()


def test_reading_saves_progress_and_session_stats(window, qtbot, mangas, store):
    path = make_cbz(mangas, "Alpha - Tome 1", pages=5)
    reader = _open(window, qtbot, path)
    ended = []
    reader.session_ended.connect(ended.append)
    reader._page_times = [time.monotonic() - 40 + i * 10 for i in range(4)]
    for _ in range(6):
        reader.next_page(animate=False)
    assert store.get_progress(path)[2] is True
    reader.close_reader()
    assert ended == [path]
    days = store.stats["devices"][store.device_id()]["days"]
    record = next(iter(days.values()))[store.key_for(path)]
    assert record["finished"] == 1 and record["pages"] >= 4


def test_wheel_scrolls_a_tall_page_before_turning(window, qtbot, mangas, store):
    store.set_reader_pref("fit_mode", 1)       # ajuster a la largeur
    store.set_reader_pref("double_page", False)
    path = make_cbz(mangas, "Webtoon - Tome 1", pages=3, size=(300, 900))
    window.resize(1200, 800)
    reader = _open(window, qtbot, path)
    window.reader_window.resize(1200, 800)
    reader.repaint()
    y0, h, vh = reader._view_geom
    assert h > vh and y0 == 0.0

    _wheel(reader, -120)
    assert reader.page == 0 and reader._view_geom[0] < 0     # a defile, pas tourne
    # rotation rapide et continue : la page defile jusqu'en bas sans tourner
    for _ in range(80):
        _wheel(reader, -120)
    y, h, vh = reader._view_geom
    assert reader.page == 0 and abs(y - (vh - h)) < 1
    # apres une pause, un cran de plus au bord tourne la page (affichee depuis son haut)
    time.sleep(0.25)
    _wheel(reader, -120)
    assert reader.page == 1
    reader.repaint()
    assert reader._view_geom[0] == 0.0


def test_touchpad_swipe_turns_a_single_page(window, qtbot, mangas, store):
    store.set_reader_pref("fit_mode", 0)
    store.set_reader_pref("double_page", False)
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1", pages=6))
    reader.repaint()
    for _ in range(60):
        _wheel(reader, -40, pixel=True)
    assert reader.page == 1


def test_pdf_is_readable(window, qtbot, mangas):
    reader = _open(window, qtbot, make_pdf(mangas, "Pluto - Tome 1", pages=3))
    assert reader.total == 3
    assert max(reader.cache[0].width(), reader.cache[0].height()) >= 1400


def test_help_overlay_escape_only_closes_help(window, qtbot, mangas):
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1"))
    QApplication.sendEvent(reader, QKeyEvent(QEvent.KeyPress, Qt.Key_F1, Qt.NoModifier))
    assert reader._help.isVisible()
    QApplication.sendEvent(reader, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not reader._help.isVisible() and window.reader is reader


def test_instance_message_opens_file_in_existing_window(window, qtbot, mangas):
    first = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1", seed=1))
    second = make_cbz(mangas, "Alpha - Tome 2", seed=2)
    window.handle_instance_message({"open": second})
    assert window.reader is not first and window.reader.path == second
