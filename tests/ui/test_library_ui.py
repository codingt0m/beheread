"""Tests d'interface de la bibliotheque (pytest-qt)."""

import time
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QWidget,
)

from beheread.core.library_model import SORTS
from tests.ui.conftest import make_cbz, scanned, visible_titles


def _set_ts(store, path, ts):
    store.progress[store.key_for(path)]["ts"] = ts


def test_first_launch_shows_welcome(window, qtbot):
    lib = window.library
    qtbot.waitUntil(lambda: not lib._scanning)
    assert lib.empty_panel.isVisible() and not lib.list.isVisible()
    assert lib.empty_title.text() == "Bienvenue dans Beheread"
    assert lib.empty_btn.isVisible()


def test_dropping_a_folder_adds_it(window, qtbot, mangas, store):
    make_cbz(mangas, "Alpha - Tome 1", seed=1)
    lib = window.library
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(mangas))])
    lib.dropEvent(QDropEvent(QPointF(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    scanned(qtbot, lib, 1)
    assert str(mangas) in store.folders()
    assert lib.list.isVisible()


def test_covers_are_kept_at_display_size(window, qtbot, mangas, store):
    make_cbz(mangas, "Alpha - Tome 1", seed=1)
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 1)
    qtbot.waitUntil(lambda: len(lib.covers.cache) == 1, timeout=10000)
    pm = next(iter(lib.covers.cache.values()))
    assert (pm.width(), pm.height()) == (lib._cover_size.width(), lib._cover_size.height())


def test_status_filters_sort_and_continue_shelf(window, qtbot, mangas, store):
    paths = {n: make_cbz(mangas, n, seed=i) for i, n in enumerate(
        ["Alpha - Tome 1", "Alpha - Tome 2", "Alpha - Tome 3", "Solo"])}
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 4)

    now = time.time()
    store.set_progress(paths["Alpha - Tome 1"], 3, 4, True)
    _set_ts(store, paths["Alpha - Tome 1"], now - 100)
    store.set_progress(paths["Solo"], 3, 5, False)
    _set_ts(store, paths["Solo"], now - 50)
    lib._rebuild_list()

    shelf = [lib.shelf.list.item(i).text() for i in range(lib.shelf.list.count())]
    assert shelf == ["Solo", "Alpha · Tome 2"]          # en cours, puis tome suivant

    lib._set_status_filter("reading")
    assert visible_titles(lib) == ["Solo"] and lib.count_label.text() == "1 tome"
    assert not lib.shelf.isVisible()
    lib._set_status_filter("finished")
    assert visible_titles(lib) == ["Alpha · Tome 1"]
    lib._set_status_filter("all")

    lib.sort_combo.setCurrentIndex([k for k, _ in SORTS].index("read"))
    assert visible_titles(lib)[:2] == ["Solo", "Alpha · Tome 1"]

    store.dismiss_continue(paths["Solo"])
    lib._rebuild_list()
    assert [lib.shelf.list.item(i).text() for i in range(lib.shelf.list.count())] == ["Alpha · Tome 2"]


def test_series_detail_and_manual_series_management(window, qtbot, mangas, store, monkeypatch):
    for i, n in enumerate(["Alpha - Tome 1", "Alpha - Tome 2", "Beta - Tome 1", "Beta - Tome 2"]):
        make_cbz(mangas, n, seed=i)
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 4)
    lib._set_group_series(True)
    lib._set_details_visible(True)
    assert sorted(visible_titles(lib)) == ["Alpha", "Beta"]

    lib.list.setCurrentRow(visible_titles(lib).index("Alpha"))
    # libelle complet (a l'ecran, un libelle trop long est raccourci avec « … »)
    def buttons():
        return [b.full_text() for b in lib.detail.findChildren(QPushButton) if b.isVisible()]
    # les boutons ajoutes a un panneau visible s'affichent aux tours suivants
    qtbot.waitUntil(lambda: "Commencer le tome 1" in buttons(), timeout=2000)
    assert lib.detail.title.text() == "Alpha"

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Alpha Deluxe", True)))
    lib._rename_series("alpha")
    assert "Alpha Deluxe" in visible_titles(lib)

    # fusion : deux « Tome 1 » cohabitent, aucun n'est masque comme doublon
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Alpha Deluxe", True)))
    lib._merge_series("beta")
    qtbot.waitUntil(lambda: visible_titles(lib) == ["Alpha Deluxe"], timeout=10000)
    assert len(lib._group_entries(lib._entries)["alpha"]) == 4


def test_failed_delete_keeps_progress(window, qtbot, mangas, store, monkeypatch):
    path = make_cbz(mangas, "Alpha - Tome 1", seed=1)
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 1)
    store.set_progress(path, 2, 4, False)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    from beheread import platforms

    def refuse(_p):
        raise OSError("fichier verrouille")
    monkeypatch.setattr(platforms, "trash_function", lambda: refuse)
    lib._delete_many([path])
    assert store.get_progress(path) == (2, 4, False) and len(lib._entries) == 1


def test_deleting_one_copy_keeps_progress_of_identical_copy(window, qtbot, mangas, store,
                                                            monkeypatch):
    """Deux copies identiques : la bibliotheque n'en affiche qu'une. Supprimer
    celle-ci apres un vrai scan ne doit pas effacer la progression, partagee
    par contenu avec l'autre copie toujours sur le disque."""
    import shutil
    first = make_cbz(mangas, "Alpha - Tome 1", seed=1)
    copy = str(mangas / "Alpha - Tome 1 copie.cbz")
    shutil.copy(first, copy)
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 1)
    shown = lib._entries[0].path
    other = copy if shown == first else first
    store.set_progress(shown, 2, 4, False)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    from beheread import platforms
    monkeypatch.setattr(platforms, "trash_function", lambda: lambda p: Path(p).unlink())
    lib._delete_many([shown])
    assert store.get_progress(other) == (2, 4, False)


def test_help_overlay_opens_and_closes(window, qtbot):
    lib = window.library
    lib._toggle_help()
    assert lib._help.isVisible()
    QApplication.sendEvent(lib._help, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not lib._help.isVisible()


def test_detail_panel_keeps_its_width_with_long_names(window, qtbot, mangas, store):
    """Un nom de fichier tres long (sans espaces, sans numero de tome) ne doit
    ni elargir le panneau ni etre coupe au bord : titre replie, boutons
    raccourcis avec « … » et texte complet en infobulle."""
    from beheread.ui.library.detail import ElidedButton
    long_name = "Parasite_Edition_originale_integrale_" + "x" * 80
    make_cbz(mangas, long_name, seed=3)
    store.set_folders([str(mangas)])
    lib = window.library
    lib._set_details_visible(True)
    lib.refresh()
    scanned(qtbot, lib, 1)
    lib.list.setCurrentRow(0)
    qtbot.wait(50)
    panel = lib.detail
    host = panel.findChild(QWidget, "detailHost")
    viewport_w = host.parentWidget().width()
    assert host.width() <= viewport_w, (host.width(), viewport_w)
    assert panel.width() == 300
    buttons = [b for b in panel.findChildren(ElidedButton) if b.isVisible()]
    assert buttons and all(b.width() <= viewport_w for b in buttons)
    assert all(b.fontMetrics().horizontalAdvance(b.text()) <= b.width() for b in buttons)
    assert panel.title.width() <= viewport_w

    # fenetre basse : le contenu defile au lieu de se tasser (aucun chevauchement)
    window.resize(1300, 500)
    qtbot.wait(50)
    assert host.height() > host.parentWidget().height()
    stack = [panel.title, panel.subtitle] + [panel.form.itemAt(i).widget()
                                             for i in range(panel.form.count())]
    stack = [w for w in stack if w is not None and w.isVisible()]
    labels_bottom = max(w.mapTo(host, w.rect().bottomLeft()).y() for w in stack)
    buttons = sorted((b for b in panel.findChildren(ElidedButton) if b.isVisible()),
                     key=lambda b: b.y())
    assert labels_bottom < buttons[0].y()
    assert all(b2.y() >= b1.y() + b1.height() for b1, b2 in zip(buttons, buttons[1:]))


def test_grid_top_fades_only_once_scrolled(window, qtbot, mangas, store):
    for i in range(12):
        # nombre de pages different : contenus uniques (pas de fusion de doublons)
        make_cbz(mangas, f"Serie{i:02d} - Tome 1", pages=2 + i, seed=i)
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 12)
    qtbot.wait(20)
    fade = lib.list._top_fade
    sb = lib.list.verticalScrollBar()
    assert sb.maximum() > 0
    sb.setValue(0)
    assert fade.strength == 0                      # grille en haut : rien n'est estompe
    sb.setValue(sb.maximum())
    assert fade.strength == 1
    vp = lib.list.viewport().geometry()
    assert fade.geometry().top() == vp.top() and fade.width() >= vp.width()
    assert fade.testAttribute(Qt.WA_TransparentForMouseEvents)


def test_continue_shelf_scrolls_with_the_grid(window, qtbot, mangas, store):
    paths = [make_cbz(mangas, f"Serie{i:02d} - Tome 1", pages=2 + i, seed=i) for i in range(12)]
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 12)
    store.set_progress(paths[0], 3, 6, False)
    lib._rebuild_list()
    qtbot.wait(20)
    host, sb = lib.list_host, lib.list.verticalScrollBar()
    extent = lib.shelf.height()
    assert lib.shelf.isVisible() and extent > 0 and sb.maximum() > 0
    assert lib.shelf.y() == 0 and lib.list.y() == extent

    # le defilement remonte d'abord la bande (et la grille avec), sans toucher la barre
    host.set_position(extent // 2)
    assert sb.value() == 0
    assert lib.shelf.y() == -(extent // 2) and lib.list.y() == extent - extent // 2
    # puis fait defiler la grille, bande entierement sortie
    host.set_position(extent + 40)
    assert sb.value() == 40 and lib.list.y() == 0 and lib.shelf.geometry().bottom() < 0

    # retour en haut par la barre (ou le clavier) : la bande reapparait
    sb.setValue(0)
    assert lib.shelf.y() == 0 and lib.list.y() == extent
    # le tri revient en haut, bande comprise
    host.set_position(extent // 2)
    lib.sort_combo.setCurrentIndex([k for k, _ in SORTS].index("read"))
    assert host.position() == 0 and lib.shelf.y() == 0


def test_folder_manager_keeps_remove_button_visible_with_long_paths(qtbot):
    from PySide6.QtWidgets import QToolButton

    from beheread.ui import theme
    from beheread.ui.library.dialogs import FolderManagerDialog
    long_path = "C:\\Users\\quelquun\\" + "Dossier~tres~long~" * 12 + "Mangas"
    dlg = FolderManagerDialog([long_path, "C:\\Mangas"], theme.colors("dark"))
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    viewport = dlg._scroll.viewport()
    buttons = dlg.findChildren(QToolButton, "fmRemove")
    assert len(buttons) == 2
    for b in buttons:
        right = b.mapTo(viewport, b.rect().topRight()).x()
        assert b.isVisible() and right < viewport.width(), (right, viewport.width())
    buttons[0].click()
    assert dlg.result_folders() == ["C:\\Mangas"]


def test_oneshots_are_described_for_anilist(window, qtbot, mangas, store):
    """Un fichier sans numero, seul de sa serie, est un one-shot pour le suivi
    AniList ; une serie numerotee garde ses numeros de tome."""
    from beheread.core.anilist_track import ONESHOT
    oneshot = make_cbz(mangas, "Errance", seed=1)
    numbered = make_cbz(mangas, "Alpha - Tome 2", seed=2)
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 2)
    store.set_progress(oneshot, 3, 4, True)
    assert lib.series_volumes_for(oneshot) == ("errance", "Errance", [(None, ONESHOT, True)])
    assert lib.series_volumes_for(numbered)[2] == [(2, "volume", False)]



def test_folders_name_series_of_generic_file_names(window, qtbot, mangas, store):
    """« Berserk/Tome 01.cbz » et « Vagabond/Tome 01.cbz » : deux series
    distinctes nommees d'apres leur dossier. Autrefois fusionnees en une serie
    « Tome », la deduplication masquait les tomes de l'une d'elles."""
    for serie, seed in (("Berserk", 1), ("Vagabond", 2)):
        (mangas / serie).mkdir()
        for n in (1, 2):
            make_cbz(mangas / serie, f"Tome 0{n}", seed=seed * 10 + n)
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 4)
    assert sorted(visible_titles(lib)) == ["Berserk · Tome 1", "Berserk · Tome 2",
                                           "Vagabond · Tome 1", "Vagabond · Tome 2"]
