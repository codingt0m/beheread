"""Tomes virtuels dans la bibliotheque : regroupement de chapitres, lecture,
renumerotation, dissociation, proposition d'apres le decoupage officiel et
remplacement par le tome officiel (ui/library/virtual_ui.py)."""

import time
from types import SimpleNamespace

from PySide6.QtWidgets import QDialog

from beheread.infra import virtual
from beheread.ui.library import virtual_ui
from tests.ui.conftest import make_cbz, scanned, visible_titles


def _number_dialog(number):
    class Dialog:
        def __init__(self, *_a, **_k):
            self.number = SimpleNamespace(value=lambda: number)

        def exec(self):
            return QDialog.Accepted
    return Dialog


def _library(window, qtbot, mangas, store, names, count=None):
    for i, name in enumerate(names):
        make_cbz(mangas, name, seed=i + 1, size=(300 + i, 420))   # contenus distincts
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, count or len(names))
    lib._set_group_series(True)
    return lib, {lib._display_title(e): e.path for e in lib._entries}


def test_chapters_grouped_into_a_virtual_volume(window, qtbot, mangas, store, monkeypatch):
    lib, paths = _library(window, qtbot, mangas, store,
                          ["Serie T01", "Serie T02"] + [f"Serie Chapitre {n}" for n in range(21, 26)])
    ch = {n: paths[f"Serie · Chapitre {n}"] for n in range(21, 26)}
    store.set_progress(ch[21], 3, 4, True)   # chapitre deja lu avant le regroupement

    monkeypatch.setattr(virtual_ui, "VirtualVolumeDialog", _number_dialog(3))
    lib._group_chapters([ch[21], ch[22], ch[23]])
    vpath = next(e.path for e in lib._entries if virtual.is_virtual(e.path))
    assert virtual.registry.chapters(vpath) == [ch[21], ch[22], ch[23]]
    assert store.get_progress(vpath) == (4, 12, False)   # reprise au chapitre 22

    lib._enter_series("serie")
    titles = visible_titles(lib)
    assert "Serie · Tome 3" in titles
    assert "Chapitre 21" not in titles and "Chapitre 24" in titles
    assert lib.next_volume(paths["Serie · Tome 2"]) == vpath
    assert lib.next_volume(vpath) == ch[24]

    # lecture : les chapitres lus en entier sont marques termines
    window.open_manga(vpath)
    reader = window.reader
    qtbot.waitUntil(lambda: reader.total == 12, timeout=5000)
    reader._go_to(9, animate=False)
    assert store.get_progress(ch[22])[2] is True
    assert not (store.get_progress(ch[23]) or (0, 0, False))[2]
    window.close_reader()

    # renumerotation : la progression suit
    monkeypatch.setattr(virtual_ui, "VirtualVolumeDialog", _number_dialog(4))
    lib._renumber_virtual(vpath)
    new_path = next(e.path for e in lib._entries if virtual.is_virtual(e.path))
    assert new_path.endswith("Serie - Tome 4.cbz") and store.get_progress(vpath) is None
    assert store.get_progress(new_path)[0] == 9

    # dissociation : les chapitres reviennent
    lib._dissolve_virtual(new_path)
    assert not any(virtual.is_virtual(e.path) for e in lib._entries)
    assert "Chapitre 21" in visible_titles(lib)


class _FakeBox:
    """QMessageBox du remplacement : « Garder les fichiers »."""
    RejectRole = AcceptRole = 0
    shown = []

    def __init__(self, *_a):
        self.buttons = []

    def setWindowTitle(self, _t):
        pass

    def setText(self, text):
        _FakeBox.shown.append(text)

    def setInformativeText(self, _t):
        pass

    def addButton(self, text, _role):
        self.buttons.append(text)
        return text

    def setDefaultButton(self, _b):
        pass

    def exec(self):
        return 0

    def clickedButton(self):
        return self.buttons[0]


def test_complete_volume_is_created_then_replaced_by_the_official_one(window, qtbot, mangas,
                                                                      store, monkeypatch):
    """Tous les chapitres d'un tome officiel sont la : le tome virtuel est
    cree tout seul ; quand le tome officiel arrive, il le remplace."""
    store.set_chapter_map("serie", {"at": time.time(), "id": "x", "v": 3,
                                    "ranges": {"2": [11, 20], "3": [21, 24]}})
    lib, paths = _library(window, qtbot, mangas, store,
                          ["Serie T01", "Serie T02"] + [f"Serie Chapitre {n}" for n in range(21, 26)],
                          count=8)   # 7 fichiers + le tome virtuel cree tout seul
    qtbot.waitUntil(lambda: any(virtual.is_virtual(e.path) for e in lib._entries), timeout=5000)
    vpath = next(e.path for e in lib._entries if virtual.is_virtual(e.path))
    assert vpath.endswith("Serie - Tome 3.cbz")
    assert len(virtual.registry.chapters(vpath)) == 4     # ch. 21 a 24, pas le 25
    assert len(store.virtual_volumes()) == 1              # pas recree a chaque reconstruction
    store.set_library_pref("show_covered_chapters", True)
    lib._enter_series("serie")
    titles = visible_titles(lib)
    assert "Suite en chapitres" in titles                # le ch. 25 reste libre
    assert "Chapitre 21" not in titles                   # dans le tome virtuel, meme affiches
    store.set_library_pref("show_covered_chapters", False)
    lib._exit_series()
    store.set_progress(vpath, 15, 16, True)

    # le tome officiel arrive : il remplace le tome virtuel
    monkeypatch.setattr(virtual_ui, "QMessageBox", _FakeBox)
    make_cbz(mangas, "Serie T03", seed=99)
    lib.refresh()
    qtbot.waitUntil(lambda: not store.virtual_volumes(), timeout=10000)
    assert _FakeBox.shown and "tome 3" in _FakeBox.shown[0]
    assert store.manual_chapter_ranges("serie") == {"3": [21, 24]}
    official = next(e.path for e in lib._entries if e.title == "Serie T03")
    assert store.get_progress(official)[2] is True       # lecture reprise
    lib._enter_series("serie")
    titles = visible_titles(lib)
    assert "Serie · Tome 3" in titles and "Chapitre 21" not in titles
    assert "Chapitre 25" in titles


def test_automatic_volume_gets_its_official_cover(window, qtbot, mangas, store, monkeypatch):
    """Tome virtuel cree d'apres le decoupage officiel : sa couverture
    officielle (MangaDex) devient sa couverture."""
    from beheread.infra import mangadex
    from tests.ui.conftest import jpeg

    asked = []
    monkeypatch.setattr(mangadex, "volume_cover",
                        lambda mid, n: asked.append((mid, n)) or jpeg("#123456", 60, 90))
    monkeypatch.setattr(window.library.chapter_maps, "ensure", lambda *a, **k: None)
    # en ligne seulement pour la couverture : les metadonnees restent hors ligne
    monkeypatch.setattr(window.library, "_online_meta", lambda: True)
    store.set_chapter_map("serie", {"at": time.time(), "id": "md-serie", "v": 3,
                                    "ranges": {"3": [21, 22]}})
    lib, _paths = _library(window, qtbot, mangas, store,
                           ["Serie T01", "Serie T02", "Serie Chapitre 21", "Serie Chapitre 22"],
                           count=5)
    qtbot.waitUntil(lambda: any(virtual.is_virtual(e.path) for e in lib._entries), timeout=5000)
    vpath = next(e.path for e in lib._entries if virtual.is_virtual(e.path))
    qtbot.waitUntil(lambda: (store.custom_cover(vpath) or {}).get("image") is not None,
                    timeout=5000)
    assert asked == [("md-serie", 3)]


def test_ungrouped_volume_is_not_created_again(window, qtbot, mangas, store):
    store.set_chapter_map("serie", {"at": time.time(), "id": "x", "v": 3, "ranges": {"2": [1, 2]}})
    lib, _paths = _library(window, qtbot, mangas, store,
                           ["Serie T01", "Serie Chapitre 1", "Serie Chapitre 2"], count=4)
    qtbot.waitUntil(lambda: any(virtual.is_virtual(e.path) for e in lib._entries), timeout=5000)
    vpath = next(e.path for e in lib._entries if virtual.is_virtual(e.path))
    # tous les chapitres sont dans le tome virtuel : pas de section de chapitres,
    # meme quand on affiche les chapitres deja inclus dans un tome
    store.set_library_pref("show_covered_chapters", True)
    lib._enter_series("serie")
    titles = visible_titles(lib)
    assert "Suite en chapitres" not in titles and "Chapitre 1" not in titles
    lib._dissolve_virtual(vpath)
    qtbot.wait(50)
    assert not store.virtual_volumes() and store.virtual_dismissed("serie") == {2}
    assert not any(virtual.is_virtual(e.path) for e in lib._entries)
