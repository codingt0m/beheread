"""Capture d'une zone de la page dans le lecteur (ui/reader/capture.py)."""

from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
)
from PySide6.QtWidgets import QApplication

from beheread.ui import theme
from beheread.ui.library.dialogs import PreferencesDialog
from beheread.ui.reader import capture
from tests.ui.conftest import make_cbz


def _image(w, h, color):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    return img


def test_capture_is_taken_at_the_scan_resolution():
    # page de 1000 x 1400 affichee en 250 x 350 : facteur 4
    page = _image(1000, 1400, "#ff0000")
    placed = [(page, QRect(0, 0, 1000, 1400), QRectF(100, 0, 250, 350))]
    sel = QRectF(50, 10, 100, 50)    # deborde a gauche de la page, sur le fond
    out = capture.compose_capture(sel, placed)
    assert (out.width(), out.height()) == (200, 200)   # 50 x 50 de page utile, x4
    assert out.pixelColor(100, 100) == QColor("#ff0000")
    assert capture.output_size(sel, placed) == out.size()
    assert capture.compose_capture(QRectF(0, 0, 50, 50), placed).isNull()


def test_capture_across_two_pages_gives_one_image():
    left, right = _image(400, 600, "#ff0000"), _image(400, 600, "#0000ff")
    placed = [(left, QRect(0, 0, 400, 600), QRectF(0, 0, 200, 300)),
              (right, QRect(0, 0, 400, 600), QRectF(200, 0, 200, 300))]
    out = capture.compose_capture(QRectF(150, 0, 100, 100), placed)
    assert (out.width(), out.height()) == (200, 200)
    assert out.pixelColor(20, 50) == QColor("#ff0000")
    assert out.pixelColor(180, 50) == QColor("#0000ff")


def test_cropped_page_maps_to_its_source_rectangle():
    page = _image(100, 100, "#ffffff")
    for x in range(50, 100):
        for y in range(100):
            page.setPixelColor(x, y, QColor("#00ff00"))
    # seule la moitie droite (recadrage) est affichee, sur 50 x 100
    placed = [(page, QRect(50, 0, 50, 100), QRectF(0, 0, 50, 100))]
    out = capture.compose_capture(QRectF(0, 0, 10, 10), placed)
    assert out.pixelColor(5, 5) == QColor("#00ff00")


def test_file_names_and_shortcut_labels(tmp_path):
    name = capture.capture_filename('Alpha: "T1"?', 7, now=0)
    assert name.startswith("Alpha T1 - p007 - ") and name.endswith(".png")
    assert not set('\\/:*?"<>|') & set(name.split(" - p")[0])
    (tmp_path / "a.png").write_bytes(b"")
    assert capture.unique_path(tmp_path, "a.png").name == "a (2).png"
    assert capture.shortcut_label("Ctrl+Shift+S") == "Ctrl + Maj + S"
    assert capture.shortcut_label("P") == "P"
    assert capture.shortcut_label("") == ""


def _drag(overlay, a, b):
    for kind, pos, buttons in ((QEvent.MouseButtonPress, a, Qt.LeftButton),
                               (QEvent.MouseMove, b, Qt.LeftButton),
                               (QEvent.MouseButtonRelease, b, Qt.NoButton)):
        QApplication.sendEvent(overlay, QMouseEvent(
            kind, QPointF(*pos), overlay.mapToGlobal(QPointF(*pos)), Qt.LeftButton,
            buttons, Qt.NoModifier))


def _key(widget, key, mods=Qt.NoModifier):
    QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, key, mods))


def _open(window, qtbot, path):
    window.open_manga(path)
    reader = window.reader
    qtbot.waitUntil(lambda: 0 in reader.cache and not reader.cache[0].isNull(), timeout=10000)
    reader.repaint()
    return reader


def test_shortcut_captures_an_area_to_clipboard_and_folder(window, qtbot, mangas, store,
                                                           tmp_path):
    store.set_reader_pref("double_page", False)
    store.set_reader_pref("capture_dir", str(tmp_path / "captures"))
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1", size=(600, 840)))
    QGuiApplication.clipboard().clear()

    _key(reader, Qt.Key_P)
    overlay = reader._capture_overlay
    assert overlay.isVisible()
    _key(overlay, Qt.Key_Right)                    # aucune touche du lecteur pendant la selection
    assert reader.page == 0

    _, page_rect = reader._placed_pages[0][0], reader._placed_pages[0][2]
    c = page_rect.center()
    _drag(overlay, (c.x() - 20, c.y() - 20), (c.x() + 20, c.y() + 20))
    assert not overlay.isVisible()

    clip = QGuiApplication.clipboard().image()
    scale = 840 / page_rect.height()
    assert abs(clip.width() - 40 * scale) <= 2 and abs(clip.height() - 40 * scale) <= 2
    assert clip.pixelColor(clip.width() // 2, clip.height() // 2).red() > 100   # COLORS[0]
    files = list((tmp_path / "captures").glob("*.png"))
    assert len(files) == 1 and files[0].name.startswith("Alpha - Tome 1 - p001 - ")
    assert reader._capture_toast.isVisible()


def test_escape_or_a_simple_click_cancels(window, qtbot, mangas, store, tmp_path):
    store.set_reader_pref("capture_dir", str(tmp_path / "captures"))
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1"))
    reader.start_capture()
    _key(reader._capture_overlay, Qt.Key_Escape)
    assert not reader._capture_overlay.isVisible() and window.reader is reader   # lecteur ouvert
    reader.start_capture()
    _drag(reader._capture_overlay, (100, 100), (102, 101))
    assert not reader._capture_overlay.isVisible()
    assert not (tmp_path / "captures").exists()


def test_shortcut_and_destination_follow_the_preferences(window, qtbot, mangas, store,
                                                         tmp_path):
    store.set_reader_pref("capture_shortcut", "Ctrl+K")
    store.set_reader_pref("capture_save", False)
    store.set_reader_pref("capture_dir", str(tmp_path / "captures"))
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1"))
    _key(reader, Qt.Key_P)
    assert not reader._capture_overlay.isVisible()
    _key(reader, Qt.Key_K, Qt.ControlModifier)
    assert reader._capture_overlay.isVisible()
    _drag(reader._capture_overlay, (300, 200), (400, 300))
    assert not (tmp_path / "captures").exists()   # presse-papiers seulement
    assert not QGuiApplication.clipboard().image().isNull()

    store.set_reader_pref("capture_shortcut", "")    # desactive
    _key(reader, Qt.Key_K, Qt.ControlModifier)
    assert not reader._capture_overlay.isVisible()


def test_default_folder_is_in_pictures():
    folder = Path(capture.default_capture_dir())
    assert folder.name == "Beheread"
    assert QKeySequence(capture.DEFAULT_SHORTCUT, QKeySequence.PortableText).count() == 1


def test_first_default_shortcut_becomes_the_new_one(store):
    store.set_reader_pref("capture_shortcut", "Ctrl+Shift+S")   # ancien defaut enregistre
    assert capture.shortcut_text(store) == "P"


def test_preferences_set_the_shortcut_and_the_folder(store, qtbot, tmp_path):
    dlg = PreferencesDialog(store, theme.colors("dark"), {})
    qtbot.addWidget(dlg)
    assert dlg.capture_keys.keySequence().toString(QKeySequence.PortableText) == "P"
    assert dlg.capture_clipboard.isChecked() and dlg.capture_save.isChecked()
    assert not dlg.capture_dir_reset.isEnabled()          # dossier par defaut
    dlg.capture_keys.setKeySequence(QKeySequence("Ctrl+K"))
    dlg.capture_keys.editingFinished.emit()
    assert store.reader_pref("capture_shortcut") == "Ctrl+K"
    dlg._set_capture_dir(str(tmp_path))
    assert store.reader_pref("capture_dir") == str(tmp_path) and dlg.capture_dir_reset.isEnabled()
    dlg.capture_save.setChecked(False)
    assert store.reader_pref("capture_save") is False and not dlg.capture_dir_row.isEnabled()
    dlg._set_capture_dir(None)
    assert store.reader_pref("capture_dir") is None
    dlg._reset_capture_keys()
    assert store.reader_pref("capture_shortcut") is None   # defaut : rien d'enregistre
    dlg.capture_keys.clear()
    dlg.capture_keys.editingFinished.emit()
    assert store.reader_pref("capture_shortcut") == ""     # desactive
