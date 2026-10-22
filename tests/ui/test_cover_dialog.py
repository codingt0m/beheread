"""Fenetre « Choisir la couverture » avec la couverture officielle (maquette 6A)."""

from beheread.ui import theme
from beheread.ui.library.dialogs import CoverDialog
from tests.ui.conftest import jpeg, make_cbz


def test_official_cover_is_offered_first(qtbot, mangas):
    path = make_cbz(mangas, "Serie T01", pages=3)
    dialog = CoverDialog("Serie · Tome 3", path, 0, theme.colors("dark"),
                         official=(lambda: jpeg("#123456", 60, 90), "Tome 3 · MangaDex"))
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._official_selected(), timeout=5000)
    assert dialog.official_status.text() == "Tome 3 · MangaDex"
    assert dialog.use.text() == "Utiliser la couverture officielle"
    qtbot.waitUntil(lambda: dialog.pages.count() == 3, timeout=5000)
    assert dialog._official_selected()          # pas detrone par la page courante

    dialog.pages.setCurrentRow(1)               # une page choisie : l'officielle ne l'est plus
    assert not dialog._official_selected() and dialog.use.text() == "Utiliser la page 2"
    dialog.official.clicked.emit()
    dialog.use.click()
    kind, image = dialog.choice
    assert kind == "image" and image.width() == 60


def test_missing_official_cover_leaves_the_pages(qtbot, mangas):
    path = make_cbz(mangas, "Serie T01", pages=2)
    dialog = CoverDialog("Serie · Tome 3", path, 0, theme.colors("dark"),
                         official=(lambda: b"", "Tome 3 · MangaDex"))
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: "pas de couverture" in dialog.official_status.text(), timeout=5000)
    assert not dialog.official.isEnabled() and not dialog._official_selected()
    qtbot.waitUntil(lambda: dialog.pages.count() == 2, timeout=5000)
    assert dialog.use.text() == "Utiliser la page 1"
    dialog.reject()


def test_official_cover_is_offered_for_ordinary_volumes_only(window, qtbot, mangas, store,
                                                             monkeypatch):
    """Tome ordinaire numerote : oui ; chapitre, edition Perfect ou hors
    ligne : non."""
    from tests.ui.conftest import scanned
    for i, name in enumerate(("Serie T03", "Serie Chapitre 40", "Boys - Perfect Edition - T01")):
        make_cbz(mangas, name, seed=i + 1)
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 3)
    by_title = {e.title: e.path for e in lib._entries}
    assert lib._official_cover_option(by_title["Serie T03"]) is None      # hors ligne
    monkeypatch.setattr(lib, "_online_meta", lambda: True)
    _fetch, source = lib._official_cover_option(by_title["Serie T03"])
    assert source == "Tome 3 · MangaDex"
    assert lib._official_cover_option(by_title["Serie Chapitre 40"]) is None
    assert lib._official_cover_option(by_title["Boys - Perfect Edition - T01"]) is None
