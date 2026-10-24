"""Tests d'interface de la synchronisation par dossier cloud (preferences,
onglet Donnees)."""

from PySide6.QtWidgets import QFileDialog

from beheread.core import sync
from beheread.services.cloud_sync import CloudSync
from beheread.ui import theme
from beheread.ui.library.dialogs import PreferencesDialog


def _prefs(store, qtbot, cs):
    dlg = PreferencesDialog(store, theme.colors("dark"), {}, cloud_sync=cs)
    qtbot.addWidget(dlg)
    return dlg


def _sync(store):
    cs = CloudSync(store)
    cs._pool.start = lambda worker: worker.run()   # synchrone
    return cs


def test_folder_choice_starts_sync_and_lists_this_device(qtbot, store, tmp_path, monkeypatch):
    cs = _sync(store)
    dlg = _prefs(store, qtbot, cs)
    assert dlg.sync_path.text() == "Aucun dossier choisi"
    assert dlg.sync_enabled.isHidden() and dlg.sync_now.isHidden()

    folder = tmp_path / "iCloud"
    folder.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(folder))
    dlg.sync_pick.click()
    assert (folder / sync.file_name(store.device_id())).exists()
    assert dlg.sync_path.text() == str(folder)
    assert dlg.sync_pick.text() == "Changer…"
    assert dlg.sync_enabled.isChecked() and not dlg.sync_enabled.isHidden()
    assert dlg.sync_status.text() == "Synchronisé"
    assert dlg.sync_warning.isHidden()
    assert not dlg.sync_devices.isHidden()

    dlg.sync_enabled.setChecked(False)
    assert not cs.enabled() and not dlg.sync_now.isEnabled()


def test_missing_folder_is_shown_as_a_warning(qtbot, store, tmp_path):
    cs = _sync(store)
    cs.set_folder(tmp_path / "Disque-debranche")
    dlg = _prefs(store, qtbot, cs)
    assert not dlg.sync_warning.isHidden()
    assert "introuvable" in dlg.sync_warning.text()
    assert dlg.sync_status.text() == ""


def test_relative_times():
    now = 1_000_000.0
    assert sync.ago(None, now) == "jamais"
    assert sync.ago(now - 10, now) == "à l'instant"
    assert sync.ago(now - 125, now) == "il y a 2 min"
    assert sync.ago(now - 3 * 3600, now) == "il y a 3 h"
    assert sync.ago(now - 3 * 86400, now).startswith("le ")
