"""Menus contextuels de la grille (ActionMenu) : actions proposees, dans
l'ordre, et declenchement de celle qui est choisie."""

import pytest
from PySide6.QtWidgets import QMenu

from beheread import platforms
from beheread.core import units
from beheread.ui.library import menus
from beheread.ui.library.constants import ROLE_IS_SERIES, ROLE_PATH, ROLE_SERIES_KEY
from tests.ui.conftest import make_cbz, scanned


@pytest.fixture
def choose(monkeypatch):
    """Remplace QMenu par un menu qui « clique » sur l'action `pick[0]` au
    lieu de s'afficher ; `seen` recoit ses libelles (--- : separateur)."""
    seen, pick = [], [None]

    class ChoosingMenu(QMenu):
        def exec(self, *_args):
            seen[:] = ["---" if a.isSeparator() else a.text() for a in self.actions()]
            # actions des sous-menus comprises (« Publiée en › Chapitres »)
            every = [x for a in self.actions()
                     for x in ([a] + (a.menu().actions() if a.menu() else []))]
            return next((a for a in every if a.text() == pick[0]), None)

    monkeypatch.setattr(menus, "QMenu", ChoosingMenu)
    return seen, pick


def _library(window, qtbot, store, mangas, grouped):
    paths = [make_cbz(mangas, f"Alpha - Tome {n}", seed=n) for n in (1, 2)]
    store.add_folder(str(mangas))
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 2)
    lib._set_group_series(grouped)
    return lib, [str(p) for p in paths]


def _open_menu_on(lib, predicate):
    item = next(lib.list.item(i) for i in range(lib.list.count()) if predicate(lib.list.item(i)))
    lib._show_context_menu(lib.list.visualItemRect(item).center())


def test_volume_menu_follows_the_four_groups_and_runs_the_chosen_one(
        window, qtbot, store, mangas, choose, monkeypatch):
    seen, pick = choose
    lib, paths = _library(window, qtbot, store, mangas, grouped=False)
    store.set_progress(paths[0], 3, 4, True)
    lib._rebuild_list()

    pick[0] = "Marquer comme non lu"
    _open_menu_on(lib, lambda it: it.data(ROLE_PATH) == paths[0])
    # ouvrir / progression (bascule : tome termine -> « non lu ») / infos et
    # rangement / supprimer
    assert seen == ["Ouvrir", "---",
                    "Marquer comme non lu", "Réinitialiser la progression…", "---",
                    "Modifier les informations…", "Choisir la couverture…", "Ranger", "Fichier",
                    "---", "Supprimer le tome…"]
    progress = store.get_progress(paths[0])
    assert progress is not None and not progress[2]   # non lu, page conservee

    # tome jamais ouvert : « Marquer comme lu », rien a reinitialiser
    pick[0] = None
    _open_menu_on(lib, lambda it: it.data(ROLE_PATH) == paths[1])
    assert "Marquer comme lu" in seen and "Marquer comme non lu" not in seen
    assert "Réinitialiser la progression…" not in seen

    # la reinitialisation demande confirmation ; « Non » ne touche a rien
    answers = []
    monkeypatch.setattr(menus.QMessageBox, "question",
                        lambda *a, **k: answers.pop(0))
    pick[0] = "Réinitialiser la progression…"
    answers.append(menus.QMessageBox.No)
    _open_menu_on(lib, lambda it: it.data(ROLE_PATH) == paths[0])
    assert store.get_progress(paths[0]) is not None
    answers.append(menus.QMessageBox.Yes)
    _open_menu_on(lib, lambda it: it.data(ROLE_PATH) == paths[0])
    assert store.get_progress(paths[0]) is None


def test_volume_submenus_hold_tidying_and_file_actions(window, qtbot, store, mangas, monkeypatch):
    lib, paths = _library(window, qtbot, store, mangas, grouped=False)
    seen = {}

    class KeepingMenu(QMenu):
        """Releve les sous-menus pendant exec (ils disparaissent avec le menu)."""

        def exec(self, *_args):
            seen.update({a.text(): [x.text() for x in a.menu().actions()]
                         for a in self.actions() if a.menu()})
            seen["default"] = self.defaultAction().text()
            return None

    monkeypatch.setattr(menus, "QMenu", KeepingMenu)
    _open_menu_on(lib, lambda it: it.data(ROLE_PATH) == paths[0])
    assert seen["Ranger"] == ["Dans une autre série…", "Sortir de la série"]
    assert seen["Fichier"] == ["Renommer le fichier…", platforms.REVEAL_LABEL,
                               "Recharger les métadonnées"]
    assert seen["default"] == "Ouvrir"


def test_selection_labels_count_volumes_and_chapters(window, qtbot, store, mangas, choose):
    seen, pick = choose
    lib, paths = _library(window, qtbot, store, mangas, grouped=False)
    lib.list.selectAll()
    _open_menu_on(lib, lambda it: it.data(ROLE_PATH) == paths[0])
    assert "Ouvrir" not in seen
    assert "Marquer 2 tomes comme lus" in seen
    assert seen[-1] == "Supprimer 2 tomes…"


def test_series_menu_sets_the_publication_nature(window, qtbot, store, mangas, choose):
    seen, pick = choose
    lib, _paths = _library(window, qtbot, store, mangas, grouped=True)
    key = next(lib.list.item(i).data(ROLE_SERIES_KEY) for i in range(lib.list.count())
               if lib.list.item(i).data(ROLE_IS_SERIES))
    pick[0] = "Chapitres"
    _open_menu_on(lib, lambda it: it.data(ROLE_IS_SERIES))
    assert seen[:3] == ["Ouvrir la série", "---", "Marquer la série comme lue"]
    assert seen[-1].startswith("Supprimer la série")
    assert store.series_nature(key) == units.CHAPTERS


def test_extensions_add_their_group_before_delete_and_cannot_break_the_menu(
        window, qtbot, store, mangas, choose, monkeypatch):
    seen, pick = choose
    lib, paths = _library(window, qtbot, store, mangas, grouped=False)
    calls = []

    def extension(menu, library, kind, target):
        calls.append((kind, target))
        menu.separator()
        menu.add("Mon action", lambda: calls.append("run"))

    def broken(*_args):
        raise RuntimeError("extension fautive")

    monkeypatch.setattr(menus, "EXTENSIONS", [])
    menus.register_extension(extension)
    menus.register_extension(extension)      # une seule fois
    menus.register_extension(broken)
    pick[0] = "Mon action"
    # menu du clic droit et bouton « ⋯ » du panneau : le meme code
    lib._show_volume_menu([paths[0]], lib.mapToGlobal(lib.rect().center()))
    assert seen[-4:] == ["---", "Mon action", "---", "Supprimer le tome…"]
    assert calls == [("volume", [paths[0]]), "run"]
