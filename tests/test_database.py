"""Tests de la base SQLite (beheread.infra.database) et de l'import des
anciens fichiers JSON par le Store."""

import json
import sqlite3

import pytest

from beheread.infra import database, storage
from beheread.infra.database import SCHEMA_VERSION, Database, DatabaseTooNew, JsonTable
from beheread.infra.storage import Store


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "MangaReaderPy"
    d.mkdir()
    monkeypatch.setattr(storage, "data_dir", lambda: d)
    return d


def _write(d, name, data):
    (d / name).write_text(json.dumps(data), encoding="utf-8")


def test_schema_is_versioned(tmp_path):
    db = Database(tmp_path / "t.db")
    assert db.version == SCHEMA_VERSION
    tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(database.TABLES) <= tables
    db.close()
    Database(tmp_path / "t.db").close()   # reouverture : aucune migration rejouee


def test_database_from_newer_version_is_refused(tmp_path):
    con = sqlite3.connect(str(tmp_path / "t.db"))
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    con.close()
    with pytest.raises(DatabaseTooNew):
        Database(tmp_path / "t.db")


def test_legacy_json_is_imported_then_archived(data_dir, tmp_path):
    manga = tmp_path / "a.cbz"
    manga.write_bytes(b"PK\x03\x04contenu" + b"\x00" * 100)
    _write(data_dir, "settings.json", {"folders": ["C:\\\\Mangas"], "reader": {"double_page": False},
                                       "ui": {"theme": "light"}})
    _write(data_dir, "progress.json", {"c1:abc": {"page": 12, "total": 40, "finished": False, "ts": 5}})
    _write(data_dir, "meta_cache.json", {"volume": {"c1:abc": {"authors": ["Miura"]}},
                                         "series": {"berserk": {"title": "Berserk"}}})
    _write(data_dir, "fingerprints.json", {str(manga): {"m": 1, "s": 2, "k": "c1:abc"}})
    _write(data_dir, "stats.json", {"devices": {"pc": {"updated": 1, "days": {}}}})
    _write(data_dir, "library_index.json", [{"path": str(manga), "title": "a"}])

    s = Store()
    assert s.folders() == ["C:\\\\Mangas"]
    assert s.ui_pref("theme") == "light" and s.reader_pref("double_page") is False
    assert s.progress["c1:abc"]["page"] == 12
    assert s.meta_cache["series"]["berserk"]["title"] == "Berserk"
    assert s.stats["devices"]["pc"]["updated"] == 1
    assert s.load_library_index()[0]["title"] == "a"
    # anciens fichiers ranges (sauvegarde), plus relus ensuite
    assert not (data_dir / "progress.json").exists()
    assert (data_dir / "legacy-json" / "progress.json").exists()

    again = Store()
    assert again.progress["c1:abc"]["page"] == 12 and again.folders() == ["C:\\\\Mangas"]


def test_damaged_legacy_file_does_not_block_import(data_dir):
    (data_dir / "progress.json").write_text("{pas du json", encoding="utf-8")
    _write(data_dir, "settings.json", {"folders": ["D:\\\\M"]})
    s = Store()
    assert s.folders() == ["D:\\\\M"] and s.progress == {}


def test_only_changed_rows_are_written(tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    repo = JsonTable("progress")
    repo.data.update({f"c1:{i}": {"page": i} for i in range(50)})
    up, de = repo.pending_changes()
    assert len(up) == 50 and not de
    with db.transaction() as cur:
        repo.write(cur, up, de)
    repo.mark_written(up, de)

    repo.data["c1:3"]["page"] = 99
    del repo.data["c1:4"]
    up, de = repo.pending_changes()
    assert [k for k, _ in up] == ["c1:3"] and de == ["c1:4"]


def test_unreadable_row_is_ignored(tmp_path):
    db = Database(tmp_path / "t.db")
    with db.transaction() as cur:
        cur.execute("INSERT INTO progress(key, value) VALUES('c1:ok', '{\"page\": 1}')")
        cur.execute("INSERT INTO progress(key, value) VALUES('c1:ko', '{casse')")
    repo = JsonTable("progress")
    repo.load(db)
    assert repo.data == {"c1:ok": {"page": 1}}


def test_everything_survives_a_restart(data_dir, tmp_path):
    manga = tmp_path / "a.cbz"
    manga.write_bytes(b"PK\x03\x04contenu-unique" + b"\x00" * 100)
    s = Store()
    s.add_folder(str(tmp_path))
    s.set_progress(str(manga), 3, 9, False)
    s.set_ui_pref("theme", "light")
    s.set_volume_meta(str(manga), {"authors": ["X"], "source": "manual"})
    s.record_reading(str(manga), 4, 60, False, "A", "A")
    s.save_library_index([{"path": str(manga), "title": "A"}])
    s.flush()
    s.db.close()

    again = Store()
    assert again.get_progress(str(manga)) == (3, 9, False)
    assert again.ui_pref("theme") == "light"
    assert again.volume_meta(str(manga))["authors"] == ["X"]
    assert again.stats["devices"][again.device_id()]["days"]
    assert again.load_library_index() == [{"path": str(manga), "title": "A"}]
    assert str(tmp_path) in again.folders()


def test_failed_import_is_retried_at_next_launch(data_dir, monkeypatch):
    """Un import interrompu (erreur disque...) ne doit pas faire « perdre »
    les anciennes donnees : il est retente au lancement suivant."""
    _write(data_dir, "progress.json", {"c1:abc": {"page": 7, "total": 20, "ts": 1}})
    real_write = JsonTable.write
    state = {"fail": True}

    def flaky_write(self, cur, upserts, deletes):
        if state["fail"]:
            raise OSError("disque plein")
        return real_write(self, cur, upserts, deletes)

    monkeypatch.setattr(JsonTable, "write", flaky_write)
    with pytest.raises(OSError):
        Store()
    assert (data_dir / "progress.json").exists()          # rien n'a ete range

    state["fail"] = False
    s = Store()
    assert s.progress["c1:abc"]["page"] == 7               # import retente et reussi
    assert not (data_dir / "progress.json").exists()


def test_import_happens_only_once(data_dir):
    _write(data_dir, "progress.json", {"c1:abc": {"page": 7, "total": 20, "ts": 1}})
    s = Store()
    s.progress["c1:abc"]["page"] = 15
    s._schedule("progress")
    s.close()
    # un ancien fichier reapparait (restauration manuelle, copie...) : ignore,
    # il n'ecrase pas la progression plus recente
    _write(data_dir, "progress.json", {"c1:abc": {"page": 7, "total": 20, "ts": 1}})
    again = Store()
    assert again.progress["c1:abc"]["page"] == 15
    again.close()


def test_fresh_install_marks_import_done(data_dir):
    s = Store()
    assert s.db.get_meta("legacy_json_import") == "aucun fichier"
    s.close()
