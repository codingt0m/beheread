"""Fixtures des tests d'interface (pytest-qt, plateforme « offscreen »).

Garde-fous : chaque test a son propre dossier de donnees temporaire, la
recherche de metadonnees en ligne est desactivee (aucun acces reseau) et le
raccourci global Ctrl+Alt+C n'est pas enregistre (il est exclusif au niveau
de Windows)."""

import zipfile

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QThreadPool
from PySide6.QtGui import QColor, QImage

from beheread.infra import storage
from beheread.infra.storage import Store

COLORS = ["#8e3b46", "#3b5b8e", "#3b8e5b", "#8e7a3b", "#5b3b8e", "#3b8e8a"]


def jpeg(color, w=300, h=420):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPEG")
    return bytes(data)


def make_cbz(folder, name, pages=4, seed=0, size=(300, 420)):
    """Archive CBZ de test ; `seed` rend son contenu unique (les doublons de
    contenu sont fusionnes par la bibliotheque)."""
    path = folder / f"{name}.cbz"
    with zipfile.ZipFile(path, "w") as z:
        for k in range(pages):
            z.writestr(f"{k:03}.jpg", jpeg(COLORS[(k + seed) % len(COLORS)], *size))
    return str(path)


def make_pdf(folder, name, pages=3):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPageSize, QPainter, QPdfWriter
    path = folder / f"{name}.pdf"
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A5))
    writer.setResolution(72)
    painter = QPainter(writer)
    for i in range(pages):
        if i:
            writer.newPage()
        painter.fillRect(QRectF(20, 20, 150, 200), QColor(COLORS[i % len(COLORS)]))
    painter.end()
    return str(path)


@pytest.fixture
def store(qapp, tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(storage, "data_dir", lambda: data)
    s = Store()
    s.set_ui_pref("online_metadata", False)   # jamais de reseau pendant les tests
    s.set_ui_pref("global_hotkey", False)
    yield s
    QThreadPool.globalInstance().waitForDone(5000)
    s.close()


@pytest.fixture
def mangas(tmp_path):
    folder = tmp_path / "mangas"
    folder.mkdir()
    return folder


@pytest.fixture
def window(qtbot, store):
    """Fenetre principale (bibliotheque) sur le Store de test."""
    from beheread.app import MainWindow
    win = MainWindow(store)
    qtbot.addWidget(win)
    win.resize(1300, 850)
    win.show()
    yield win
    if win.reader is not None:
        win.reader.release()
    QThreadPool.globalInstance().waitForDone(5000)


def scanned(qtbot, lib, count, timeout=10000):
    qtbot.waitUntil(lambda: len(lib._entries) == count and not lib._scanning, timeout=timeout)


def visible_titles(lib):
    return [lib.list.item(i).text() for i in range(lib.list.count())
            if not lib.list.isRowHidden(i)]
