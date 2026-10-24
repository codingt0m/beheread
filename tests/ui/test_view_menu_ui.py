"""Menu « Affichage » de la barre d'outils (maquette M3) : reglages de vue
appliques et enregistres tout de suite, curseur de taille, touche I."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QListWidget, QSlider, QToolButton

from tests.ui.conftest import make_cbz, scanned, visible_titles


def _library(window, qtbot, store, mangas):
    for n in (1, 2):
        make_cbz(mangas, f"Alpha - Tome {n}", seed=n)
    make_cbz(mangas, "Beta", seed=9)
    store.add_folder(str(mangas))
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 3)
    return lib


def test_size_slider_left_the_header_for_the_view_menu(window):
    lib = window.library
    assert not lib.header.findChildren(QSlider)
    assert lib.view_btn in lib.toolbar.findChildren(QToolButton)
    assert lib.view_btn.menu() is lib.view_menu
    texts = [a.text() for a in lib.view_menu.actions() if a.text()]
    assert texts[:2] == ["Grille", "Liste compacte"]
    assert "Regrouper par série" in texts and "Panneau d'informations" in texts


def test_view_settings_apply_and_save_immediately(window, qtbot, store, mangas):
    lib = _library(window, qtbot, store, mangas)

    lib._view_toggles["group_series"].trigger()
    assert store.library_pref("group_series") is True
    assert sorted(visible_titles(lib)) == ["Alpha", "Beta"]

    lib._view_actions["list"].trigger()
    assert store.library_pref("view_mode") == "list"
    assert lib.list.viewMode() == QListWidget.ListMode
    lib._sync_view_menu()
    assert not lib._size_row.isEnabled()          # la taille ne vaut qu'en grille
    lib._view_actions["grid"].trigger()
    assert lib.list.viewMode() == QListWidget.IconMode

    lib._view_toggles["show_continue"].trigger()
    assert store.library_pref("show_continue") is False and lib._show_continue is False

    # reglage change ailleurs (Preferences) : le menu le reflete a l'ouverture
    store.set_library_pref("show_missing", False)
    lib._sync_view_menu()
    assert not lib._view_toggles["show_missing"].isChecked()


def test_i_key_toggles_the_detail_panel_from_the_grid_only(window, qtbot, store, mangas):
    lib = _library(window, qtbot, store, mangas)
    window.show()
    qtbot.waitExposed(window)
    lib.list.setFocus()
    assert not lib.detail.isVisible()
    QTest.keyClick(lib.list, Qt.Key_I)
    assert lib.detail.isVisible() and store.library_pref("show_details") is True

    # pendant une saisie dans la recherche, « i » s'ecrit
    lib.search_edit.setFocus()
    QTest.keyClicks(lib.search_edit, "i")
    assert lib.search_edit.text() == "i"
    assert lib.detail.isVisible()
