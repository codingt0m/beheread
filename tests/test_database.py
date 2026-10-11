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
    assert s.reading_log.export()["devices"]["pc"]["updated"] == 1
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
    assert again.reading_log.export()["devices"][again.device_id()]["days"]
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


def _schema_2_database(path, settings, index):
    """Base telle que la laissait une version a schema 2 (avant le decoupage
    des reglages par tome)."""
    con = sqlite3.connect(str(path), isolation_level=None)
    cur = con.cursor()
    for version in (1, 2):
        for step in database.MIGRATIONS[version]:
            step(cur) if callable(step) else cur.execute(step)
    for key, value in settings.items():
        cur.execute("INSERT INTO settings VALUES (?, ?)", (key, json.dumps(value)))
    cur.execute("INSERT INTO library_index VALUES ('entries', ?)", (json.dumps(index),))
    for key in (storage.LEGACY_IMPORT_KEY, storage.FINISHED_HISTORY_KEY):
        cur.execute("INSERT INTO app_meta VALUES (?, 'fait')", (key,))
    cur.execute("PRAGMA user_version = 2")
    con.close()


def test_schema_2_data_moves_to_its_own_tables(data_dir):
    settings = {
        "folders": ["D:/Mangas"], "reader": {"double_page": False},
        "added": {"c1:a": 5.0}, "pages": {"c1:a": 40},
        "series_overrides": {"c1:a": "Berserk"}, "volume_direction": {"c1:b": True},
        "continue_dismissed": {"c1:a": 7.0},
        "anilist": {"user": "tom", "map": {"berserk": {"id": 1}},
                    "pending": {"vagabond": {"name": "Vagabond"}}, "last": {"berserk": {"ts": 1}}},
    }
    index = [{"path": "B.cbz", "title": "B"}, {"path": "A.cbz", "title": "A"}]
    _schema_2_database(data_dir / storage.DB_NAME, settings, index)

    for s in (Store(), Store()):   # migration, puis relecture telle quelle
        assert s.db.version == SCHEMA_VERSION == 3
        assert s._added == {"c1:a": 5.0} and s._pages == {"c1:a": 40}
        assert s._overrides == {"c1:a": "Berserk"} and s._directions == {"c1:b": True}
        assert s.continue_dismissed() == {"c1:a": 7.0}
        assert s.anilist_series("map") == {"berserk": {"id": 1}}
        assert s.anilist_series("pending") == {"vagabond": {"name": "Vagabond"}}
        assert s.anilist() == {"user": "tom"}
        assert s.folders() == ["D:/Mangas"] and s.reader_pref("double_page") is False
        assert [e["title"] for e in s.load_library_index()] == ["B", "A"]   # ordre garde
        assert not set(storage.SPLIT_SETTINGS) & set(s.settings)
        s.close()
    assert (data_dir / "beheread-v2.bak").exists()   # copie d'avant migration
    con = sqlite3.connect(str(data_dir / storage.DB_NAME))
    try:
        assert con.execute("SELECT COUNT(*) FROM settings WHERE key = 'added'").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM library_index").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM library_entries").fetchone()[0] == 2
    finally:
        con.close()


def _spy(repo, method):
    calls = []
    original = getattr(repo, method)

    def spy(*args):
        calls.append(args)
        return original(*args)
    setattr(repo, method, spy)
    return calls


def test_a_page_turn_serializes_only_its_volume(data_dir, tmp_path):
    s = Store()
    for i in range(30):
        s.progress[f"c1:{i}"] = {"page": i, "total": 50, "finished": False, "ts": 1}
    s._schedule("progress")
    s.flush()
    manga = tmp_path / "a.cbz"
    manga.write_bytes(b"PK\x03\x04tome-unique" + b"\x00" * 100)
    key = s.key_for(str(manga))
    calls = _spy(s._repos["progress"], "pending_changes")
    s.set_progress(str(manga), 3, 50, False)
    s.flush()
    assert calls == [({key},)]
    assert Store().get_progress(str(manga)) == (3, 50, False)


def test_library_index_writes_only_changed_rows(data_dir):
    s = Store()
    entries = [{"path": f"{i}.cbz", "title": str(i)} for i in range(20)]
    s.save_library_index(entries)
    writes = _spy(s._repos["entries"], "write")
    entries[-1] = {"path": "19.cbz", "title": "renomme"}
    s.save_library_index(entries)
    (_cur, upserts, deletes), = writes
    assert [k for k, _v in upserts] == ["19.cbz"] and deletes == []
    assert Store().load_library_index()[-1]["title"] == "renomme"


def test_maintenance_compacts_a_mostly_empty_database(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "VACUUM_MIN_PAGES", 1)
    db = Database(tmp_path / "b.db")
    with db.transaction() as cur:
        cur.executemany("INSERT INTO progress VALUES (?, ?)",
                        [(f"k{i}", "x" * 500) for i in range(2000)])
    with db.transaction() as cur:
        cur.execute("DELETE FROM progress")
    assert db.conn.execute("PRAGMA freelist_count").fetchone()[0] > 0
    db.maintenance()
    assert db.conn.execute("PRAGMA freelist_count").fetchone()[0] == 0
    db.close()
