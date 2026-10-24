"""Tests de la synchronisation par dossier cloud (core/sync.py et
services/cloud_sync.py). Deux « appareils » (deux Store) partagent un dossier
temporaire ; le thread de synchronisation est execute sur place."""

import json

from beheread.core import sync
from beheread.infra import storage
from beheread.infra.storage import Store
from beheread.services.cloud_sync import CloudSync
from tests.test_storage import _make_manga

DEV_A, DEV_B = "a" * 32, "b" * 32


def test_peer_files_ignore_own_file_and_cloud_leftovers():
    names = [sync.file_name(DEV_A), sync.file_name(DEV_B),
             f"beheread-sync-{DEV_B} (1).json",          # copie en conflit
             f"{sync.file_name(DEV_B)}.123-4.tmp",       # ecriture en cours
             "notes.txt"]
    assert sync.peer_files(names, DEV_A) == [sync.file_name(DEV_B)]


def test_signature_ignores_export_date():
    data = {"format": "beheread-backup", "progress": {"c1:x": {"page": 3}}, "exported": 1}
    assert sync.signature(data) == sync.signature(dict(data, exported=2))
    assert sync.signature(data) != sync.signature(dict(data, progress={}))


def _device(tmp_path, monkeypatch, name, folder):
    d = tmp_path / name
    d.mkdir()
    monkeypatch.setattr(storage, "data_dir", lambda d=d: d)
    store = Store()
    cs = CloudSync(store)
    cs._pool.start = lambda worker: worker.run()   # synchrone : _on_done appele sur place
    cs.set_folder(folder)
    return store, cs


def test_progress_travels_between_devices(qapp, tmp_path, monkeypatch):
    folder = tmp_path / "iCloud"
    folder.mkdir()
    manga = _make_manga(tmp_path, "a.cbz")
    pc, pc_sync = _device(tmp_path, monkeypatch, "pc", folder)
    mac, mac_sync = _device(tmp_path, monkeypatch, "mac", folder)
    synced = []
    mac_sync.synced.connect(synced.append)

    pc.set_progress(manga, 7, 10, False)
    pc.record_reading(manga, 7, 210, False, "A", "A")
    pc_sync.sync_now()
    own = folder / sync.file_name(pc.device_id())
    assert json.loads(own.read_text(encoding="utf-8"))["progress"]

    mac_sync.sync_now()
    assert mac.get_progress(manga) == (7, 10, False)
    assert synced and synced[0]["progress"] == 1
    assert pc.device_id() in mac_sync.peers()
    assert "1 tome" in mac_sync.status
    # fichier deja fusionne et lecture inchangee : rien n'est relu ni recompte
    mac_sync._debounce.stop()
    mac_sync.sync_now()
    assert len(synced) == 1
    assert mac.reading_log.totals("0000-01-01", "9999-12-31").pages == 7

    # et dans l'autre sens : la lecture la plus recente l'emporte
    mac.set_progress(manga, 9, 10, False)
    mac_sync.sync_now()
    pc_sync.sync_now()
    assert pc.get_progress(manga) == (9, 10, False)


def test_unchanged_reading_is_not_rewritten(qapp, tmp_path, monkeypatch):
    """Rien n'est reecrit tant que la lecture n'a pas change : le client
    cloud n'a rien a renvoyer toutes les 5 minutes."""
    folder = tmp_path / "Dropbox"
    folder.mkdir()
    pc, pc_sync = _device(tmp_path, monkeypatch, "pc", folder)
    own = folder / sync.file_name(pc.device_id())
    before = own.stat().st_mtime_ns
    own.write_text(own.read_text(encoding="utf-8"), encoding="utf-8")   # meme contenu, date touchee
    touched = own.stat().st_mtime_ns
    pc_sync.sync_now()
    assert own.stat().st_mtime_ns == touched and touched >= before


def test_missing_folder_keeps_everything_for_later(qapp, tmp_path, monkeypatch):
    folder = tmp_path / "Disque"
    folder.mkdir()
    manga = _make_manga(tmp_path, "a.cbz")
    pc, pc_sync = _device(tmp_path, monkeypatch, "pc", folder)
    import shutil
    shutil.rmtree(folder)   # disque debranche
    pc.set_progress(manga, 4, 10, False)
    pc_sync.sync_now()
    assert "introuvable" in pc_sync.status
    folder.mkdir()     # dossier de retour : la lecture faite entre-temps part
    pc_sync.sync_now()
    data = json.loads((folder / sync.file_name(pc.device_id())).read_text(encoding="utf-8"))
    assert any(v["page"] == 4 for v in data["progress"].values())


def test_damaged_peer_file_is_skipped(qapp, tmp_path, monkeypatch):
    folder = tmp_path / "OneDrive"
    folder.mkdir()
    (folder / sync.file_name(DEV_B)).write_text("{pas du json", encoding="utf-8")
    pc, pc_sync = _device(tmp_path, monkeypatch, "pc", folder)
    assert pc_sync.status == "Synchronisé"
    assert not pc_sync.peers()


def test_push_on_close_writes_the_last_session(qapp, tmp_path, monkeypatch):
    folder = tmp_path / "iCloud"
    folder.mkdir()
    manga = _make_manga(tmp_path, "a.cbz")
    pc, pc_sync = _device(tmp_path, monkeypatch, "pc", folder)
    pc.set_progress(manga, 8, 10, False)
    pc_sync.push_on_close()
    data = json.loads((folder / sync.file_name(pc.device_id())).read_text(encoding="utf-8"))
    assert any(v["page"] == 8 for v in data["progress"].values())


def test_disabled_sync_does_nothing(qapp, tmp_path, monkeypatch):
    folder = tmp_path / "iCloud"
    folder.mkdir()
    pc, pc_sync = _device(tmp_path, monkeypatch, "pc", folder)
    (folder / sync.file_name(pc.device_id())).unlink()
    pc_sync.set_enabled(False)
    pc_sync.sync_now()
    pc_sync.push_on_close()
    assert not list(folder.iterdir())
