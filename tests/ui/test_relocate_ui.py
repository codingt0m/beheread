"""Deplacer des tomes vers un autre dossier source (ui/library/relocate_ui.py)."""

from PySide6.QtWidgets import QDialog, QMenu

from beheread.ui.library import relocate_ui
from tests.ui.conftest import make_cbz, scanned


class _Accept:
    def __init__(self, *_a, **_k):
        pass

    def exec(self):
        return QDialog.Accepted


def test_series_moves_to_another_source_with_its_reading(window, qtbot, tmp_path, store,
                                                         monkeypatch):
    local, cloud = tmp_path / "local", tmp_path / "cloud"
    (local / "Serie").mkdir(parents=True)
    cloud.mkdir()
    paths = [make_cbz(local / "Serie", f"Serie T0{n}", seed=n) for n in (1, 2)]
    (cloud / "Serie").mkdir()
    make_cbz(cloud / "Serie", "Serie T02", seed=2)   # deja present a destination
    store.set_folders([str(local), str(cloud)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 2)    # meme contenu : une seule entree pour le T02
    store.set_progress(paths[0], 3, 4, True)

    messages = []
    monkeypatch.setattr(relocate_ui, "MoveConfirmDialog", _Accept)
    monkeypatch.setattr(relocate_ui.QMessageBox, "information",
                        lambda *a: messages.append(a[2]))
    lib._move_paths(paths, str(cloud))
    moved = cloud / "Serie" / "Serie T01.cbz"
    qtbot.waitUntil(lambda: moved.exists() and not lib._move_jobs, timeout=10000)
    assert not (local / "Serie" / "Serie T01.cbz").exists()
    assert (local / "Serie" / "Serie T02.cbz").exists()          # conflit : laisse en place
    assert messages and "Serie T02.cbz" in messages[0]
    assert store.get_progress(str(moved))[2] is True              # la lecture suit


def test_move_menu_lists_the_other_sources(window, qtbot, tmp_path, store):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir()
    b.mkdir()
    path = make_cbz(a, "Solo T01", seed=1)
    store.set_folders([str(a), str(b)])
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 1)
    menu = QMenu()
    actions = lib._add_move_menu(menu, [path])
    by_folder = {folder: act for act, folder in actions.items()}
    assert not by_folder[str(a)].isEnabled() and by_folder[str(b)].isEnabled()
    store.set_folders([str(a)])
    assert lib._add_move_menu(QMenu(), [path]) == {}              # un seul dossier
