"""Comportements propres a macOS, testables sur tous les systemes : fichiers
transmis par le Finder (QFileOpenEvent) et sortie du plein ecran du lecteur.
Ce qui ne se simule pas (vrai Finder, animation du plein ecran) est dans la
liste de verification docs/TEST-MACOS.md."""

from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication

from tests.ui.conftest import make_cbz


def test_file_open_events_are_forwarded(qapp, tmp_path):
    from beheread.app import FileOpenEvents
    received = []
    events = FileOpenEvents()
    events.opened.connect(received.append)
    qapp.installEventFilter(events)
    try:
        QApplication.sendEvent(qapp, QFileOpenEvent(str(tmp_path / "Alpha - Tome 1.cbz")))
    finally:
        qapp.removeEventFilter(events)
    assert received == [str(tmp_path / "Alpha - Tome 1.cbz")]


def test_finder_file_at_launch_opens_the_reader_alone(window, qtbot, mangas):
    path = make_cbz(mangas, "Alpha - Tome 1")
    window.hide()
    window.show_library_unless_file_arrives(delay_ms=50)
    window.handle_file_open(path)
    assert window.direct_mode and window.reader is not None and window.reader.path == path
    qtbot.wait(150)                     # le delai ecoule n'affiche pas la bibliotheque
    assert not window.isVisible()


def test_library_shows_when_no_file_arrives_at_launch(window, qtbot):
    window.hide()
    window.show_library_unless_file_arrives(delay_ms=20)
    qtbot.waitUntil(window.isVisible, timeout=2000)
    assert not window.direct_mode and window.reader is None


def test_finder_file_after_launch_opens_in_the_running_app(window, qtbot, mangas):
    path = make_cbz(mangas, "Alpha - Tome 1")
    window.handle_file_open(path)
    assert not window.direct_mode and window.reader.path == path


def test_leaving_the_reader_outside_fullscreen_is_immediate(qtbot):
    from beheread.app import ReaderWindow
    win = ReaderWindow()
    qtbot.addWidget(win)
    called = []
    win.leave_fullscreen_then(lambda: called.append(True))
    assert called == [True]
