"""Captures d'ecran de Beheread sur une fausse bibliotheque, pour verifier le
rendu sur un systeme qu'on n'a pas sous la main (la CI macOS les publie en
artefact : .github/workflows/ci.yml).

    python tools/screenshots.py <dossier de sortie>

Les donnees sont creees dans un dossier jetable : ni la vraie bibliotheque
ni les vraies preferences ne sont touchees. Les fenetres sont rendues hors
ecran (WA_DontShowOnScreen) mais avec la plateforme graphique du systeme,
donc ses vraies polices (la plateforme « offscreen » n'en a pas)."""

import datetime as dt
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, Qt, QThreadPool
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from beheread.infra import storage

SIZE = (1440, 900)
SERIES = [("Berserk", 4, "#7a2e2e"), ("Vagabond", 3, "#2e4a7a"), ("Pluto", 2, "#2e6a4f"),
          ("Monster", 2, "#6a5a2e"), ("Le Pays des Purs", 1, "#5a2e6a")]


def _page(title, subtitle, color, w=600, h=860) -> bytes:
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    p = QPainter(img)
    p.setPen(QColor("#f2f2f2"))
    font = QFont()
    font.setPixelSize(64)
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRect(30, 220, w - 60, 300), Qt.AlignCenter | Qt.TextWordWrap, title)
    font.setPixelSize(40)
    font.setBold(False)
    p.setFont(font)
    p.drawText(QRect(30, 520, w - 60, 120), Qt.AlignCenter, subtitle)
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPEG", 85)
    return bytes(data)


def _make_library(folder: Path) -> dict:
    paths = {}
    for name, volumes, color in SERIES:
        for v in range(1, volumes + 1):
            path = folder / f"{name} - Tome {v}.cbz"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("000.jpg", _page(name, f"Tome {v}", color))
                for k in range(1, 6):
                    z.writestr(f"{k:03}.jpg", _page(name, f"Page {k + 1}", "#ddd8cf"))
            paths[(name, v)] = str(path)
    return paths


def _wait(app, condition, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return
        time.sleep(0.02)
    raise TimeoutError("condition non remplie")


def _settle(app, seconds=0.4):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


def _offscreen(widget, size=SIZE):
    widget.setAttribute(Qt.WA_DontShowOnScreen)
    widget.resize(*size)
    widget.show()


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="beheread-captures-"))
    data, mangas = work / "data", work / "mangas"
    data.mkdir()
    mangas.mkdir()
    storage.data_dir = lambda: data

    app = QApplication(sys.argv)
    from beheread.app import MainWindow, apply_theme
    from beheread.ui import theme
    from beheread.ui.library.dialogs import PreferencesDialog
    from beheread.ui.reader.widget import ReaderWidget
    from beheread.ui.stats_view import StatsDialog

    store = storage.Store()
    store.set_ui_pref("online_metadata", False)   # aucun acces reseau
    store.set_ui_pref("global_hotkey", False)
    paths = _make_library(mangas)
    today = dt.date.today()
    for (name, v), path in paths.items():         # progression et journal de lecture
        if name == "Berserk" and v <= 2 or name == "Pluto" and v == 1:
            store.set_progress(path, 5, 6, True)
            store.record_reading(path, 6, 900, True, f"{name} - Tome {v}", name,
                                 date=today - dt.timedelta(days=3 * v))
        elif (name, v) in (("Berserk", 3), ("Vagabond", 1)):
            store.set_progress(path, 2, 6, False)
            store.record_reading(path, 3, 420, False, f"{name} - Tome {v}", name,
                                 date=today - dt.timedelta(days=1))
    store.set_folders([str(mangas)])
    apply_theme(app, "dark")
    shots = []

    def grab(widget, name, wait=0.4):
        _settle(app, wait)   # fondus d'apparition termines
        widget.grab().save(str(out / f"{name}.png"))
        shots.append(name)

    # -- bibliotheque
    window = MainWindow(store)
    _offscreen(window)
    lib = window.library
    lib.refresh()
    _wait(app, lambda: len(lib._entries) == len(paths) and not lib._scanning)
    _wait(app, lambda: len(lib.covers.cache) >= len(paths), timeout=20)
    grab(window, "01-bibliotheque")
    lib._toggle_help()
    grab(window, "02-bibliotheque-aide")
    lib._toggle_help()
    store.set_library_pref("show_details", True)
    lib._set_details_visible(True)
    lib.list.setCurrentRow(0)
    grab(window, "03-bibliotheque-details")

    # -- preferences, onglet par onglet
    prefs = PreferencesDialog(store, theme.colors("dark"), {})
    _offscreen(prefs, (prefs.sizeHint().width(), prefs.sizeHint().height()))
    for i in range(prefs.tabs.count()):
        prefs.tabs.setCurrentIndex(i)
        grab(prefs, f"04-preferences-{i + 1}-{prefs.tabs.tabText(i).lower()}")
    prefs.close()

    # -- statistiques
    library = {"unread": 6, "reading": 2, "finished": 4, "remaining_pages": 48,
               "unknown_pages": 0}
    stats = StatsDialog(store, library, "dark")
    stats.setWindowState(Qt.WindowNoState)
    _offscreen(stats)
    stats.fit_height()
    grab(stats, "05-statistiques")
    stats.close()

    # -- lecteur (dans un conteneur : pas de vrai plein ecran pendant la capture)
    host = QWidget()
    QVBoxLayout(host).setContentsMargins(0, 0, 0, 0)
    reader = ReaderWidget(paths[("Berserk", 3)], store)
    host.layout().addWidget(reader)
    _offscreen(host)
    _wait(app, lambda: 0 in reader.cache and not reader.cache[0].isNull())
    reader.set_fullscreen(True)
    reader._show_chrome()
    grab(host, "06-lecteur", wait=1.2)
    reader._toggle_help()
    grab(host, "07-lecteur-aide", wait=1.2)
    reader._toggle_help()
    for _ in range(len(reader.cache) + 6):
        if reader.end_card.isVisible():
            break
        reader.next_page(animate=False)
        _settle(app, 0.1)
    grab(host, "08-fin-de-tome", wait=1.2)
    reader.release()

    QThreadPool.globalInstance().waitForDone(5000)
    store.close()
    print("\n".join(f"{out / name}.png" for name in shots))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
