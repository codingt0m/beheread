"""Tests de l'en-tete allege (recherche centree), des reglages deplaces dans
les preferences et du menu de la bande « Continuer la lecture »."""

from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QMenu, QToolButton

from beheread.ui.library import menus
from beheread.ui.library.dialogs import PreferencesDialog
from tests.ui.conftest import make_cbz, scanned


def _search_offset(lib):
    """Ecart (px) entre le centre de la recherche et celui de l'en-tete."""
    geo = lib.search_edit.geometry()
    return abs((geo.left() + geo.right() + 1) / 2 - lib.header.width() / 2)


def test_header_keeps_the_essentials_and_centers_the_search(window, qtbot, mangas, store):
    lib = window.library
    names = {b.accessibleName() for b in lib.header.findChildren(QToolButton, "headerBtn")}
    assert names == {"Gérer les dossiers sources", "Rafraîchir",
                     "Statistiques de lecture", "Préférences"}
    for removed in ("btn_theme", "btn_view", "btn_details", "btn_help", "btn_group"):
        assert not hasattr(lib, removed)

    for width in (1300, 1101, 1640):
        window.resize(width, 850)
        qtbot.wait(20)
        assert _search_offset(lib) <= 0.5, width
    # les deux cotes ont un contenu de largeur differente, mais la meme largeur
    assert lib._header_left.width() == lib._header_right.width()
    assert lib._header_left.sizeHint().width() != lib._header_right.sizeHint().width()

    # dans un dossier de serie, le bouton de retour (nom long) elargit le cote
    # gauche : la recherche ne bouge pas
    long_name = "Une Serie Au Nom Vraiment Tres Long Pour Un En Tete De Fenetre"
    for i in (1, 2):
        make_cbz(mangas, f"{long_name} - Tome {i}", seed=i)
    store.set_folders([str(mangas)])
    lib._set_group_series(True)
    lib.refresh()
    scanned(qtbot, lib, 2)
    lib._enter_series(lib.list.item(0).data(lib_role_series_key()))
    qtbot.wait(20)
    assert lib.btn_back.isVisible() and lib.btn_back.text().endswith("…")
    assert long_name in lib.btn_back.toolTip()
    assert _search_offset(lib) <= 0.5
    lib._exit_series()
    qtbot.wait(20)
    assert not lib.btn_back.isVisible() and _search_offset(lib) <= 0.5


def lib_role_series_key():
    from beheread.ui.library.constants import ROLE_SERIES_KEY
    return ROLE_SERIES_KEY


def test_view_mode_and_detail_panel_are_set_in_preferences(window, qtbot, mangas, store,
                                                           monkeypatch):
    for i, name in enumerate(["Alpha - Tome 1", "Alpha - Tome 2", "Beta - Tome 1"]):
        make_cbz(mangas, name, seed=i)
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 3)
    assert lib.list.viewMode() == QListWidget.IconMode and not lib.detail.isVisible()
    titles = lambda: sorted(lib.list.item(i).text() for i in range(lib.list.count()))
    assert titles() == ["Alpha · Tome 1", "Alpha · Tome 2", "Beta · Tome 1"]

    def choose(view_index, details, grouped=False):
        def fake_exec(dlg):
            dlg.view_mode.setCurrentIndex(view_index)
            dlg.show_details.setChecked(details)
            dlg.group_series.setChecked(grouped)
            return QDialog.Accepted
        monkeypatch.setattr(PreferencesDialog, "exec", fake_exec)
        lib.open_preferences()

    choose(1, True)
    assert store.library_pref("view_mode") == "list" and store.library_pref("show_details") is True
    assert lib.list.viewMode() == QListWidget.ListMode and lib.detail.isVisible()
    choose(0, False)
    assert store.library_pref("view_mode") == "grid"
    assert lib.list.viewMode() == QListWidget.IconMode and not lib.detail.isVisible()

    # regroupement par serie : meme chemin, plus de bouton dans l'en-tete
    choose(0, False, grouped=True)
    assert store.library_pref("group_series") is True
    assert titles() == ["Alpha", "Beta · Tome 1"]
    lib._enter_series("alpha")
    choose(0, False, grouped=False)        # decocher sort aussi du dossier ouvert
    assert store.library_pref("group_series") is False and lib._current_series is None
    assert titles() == ["Alpha · Tome 1", "Alpha · Tome 2", "Beta · Tome 1"]


def test_preferences_list_every_keyboard_shortcut(qtbot, store):
    from beheread.ui import theme
    dlg = PreferencesDialog(store, theme.colors("dark"), {})
    qtbot.addWidget(dlg)
    titles = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert titles == ["Général", "Lecteur", "Données", "AniList", "Raccourcis"]
    page = dlg.tabs.widget(titles.index("Raccourcis"))
    texts = {lab.text() for lab in page.findChildren(QLabel)}
    assert {"Dans la bibliothèque", "Dans le lecteur"} <= texts
    assert {"Ctrl + F", "F5", "Ambilight", "Rechercher"} <= texts   # bibliotheque et lecteur
    # le dialogue tient dans l'ecran (il n'est plus plafonne aux 2/3 par Qt)
    assert dlg.height() <= dlg.screen().availableGeometry().height()


def test_reader_settings_in_preferences(qtbot, store):
    from beheread.ui import theme
    store.set_reader_pref("fit_mode", 0)       # ancien « fenetre »
    dlg = PreferencesDialog(store, theme.colors("dark"), {})
    qtbot.addWidget(dlg)
    assert [dlg.fit.itemText(i) for i in range(dlg.fit.count())] == [
        "Ajuster à la hauteur", "Ajuster à la largeur"]
    assert dlg.fit.currentIndex() == 0 and not dlg.ambilight.isChecked()
    dlg.ambilight.setChecked(True)
    dlg.fit.setCurrentIndex(1)
    dlg.save()
    assert store.reader_pref("ambilight") is True and store.reader_pref("fit_mode") == 1


def test_continue_shelf_can_reset_progress(window, qtbot, mangas, store, monkeypatch):
    paths = [make_cbz(mangas, f"Alpha - Tome {i}", seed=i) for i in (1, 2)]
    store.set_folders([str(mangas)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 2)
    store.set_progress(paths[0], 4, 4, True)    # termine : « A suivre » propose le tome 2
    lib._rebuild_list()
    shelf = lambda: [lib.shelf.list.item(i).text() for i in range(lib.shelf.list.count())]
    assert shelf() == ["Alpha · Tome 2"]

    seen = []

    class ChoosingMenu(QMenu):
        """Menu qui « clique » sur l'action voulue au lieu de s'afficher."""

        def exec(self, *_args):
            seen[:] = [a.text() for a in self.actions()]
            return next((a for a in self.actions()
                         if a.text() == "Réinitialiser la progression"), None)

    monkeypatch.setattr(menus, "QMenu", ChoosingMenu)

    # tome suivant, pas encore commence : rien a reinitialiser
    lib._show_shelf_menu(paths[1], lib.mapToGlobal(lib.rect().center()))
    assert "Réinitialiser la progression" not in seen
    assert store.get_progress(paths[0]) is not None

    # tome en cours : l'action efface sa progression, il quitte la bande
    store.set_progress(paths[1], 2, 4, False)
    lib._rebuild_list()
    lib._show_shelf_menu(paths[1], lib.mapToGlobal(lib.rect().center()))
    assert "Réinitialiser la progression" in seen
    assert store.get_progress(paths[1]) is None
    assert store.get_progress(paths[0]) == (4, 4, True)   # les autres tomes ne bougent pas
    assert shelf() == ["Alpha · Tome 2"]                  # redevenu « tome suivant », non commence
