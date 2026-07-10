"""Tests de la persistance (storage.py) : identite par contenu, migration des
entrees indexees par chemin, decalage de parite, decoupage de settings.json.

`data_dir()` s'appuie sur %APPDATA% ; chaque test le redirige vers un dossier
temporaire isole.
"""

import json

import pytest

import storage
from storage import Store


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    # hors Windows, data_dir() ignore APPDATA : on force le dossier de donnees
    monkeypatch.setattr(storage, "data_dir", lambda: tmp_path / "MangaReaderPy")
    (tmp_path / "MangaReaderPy").mkdir(parents=True, exist_ok=True)
    return Store()


def _make_manga(dir_path, name, content=b"chapitre un, contenu unique"):
    p = dir_path / name
    p.write_bytes(b"PK\x03\x04" + content + b"\x00" * 200)
    return str(p)


def test_progress_roundtrip(store, tmp_path):
    path = _make_manga(tmp_path, "a.cbz")
    store.set_progress(path, 5, 100, False)
    assert store.get_progress(path) == (5, 100, False)


def test_progress_survives_rename(store, tmp_path):
    """Le coeur de l'identite par contenu : deplacer/renommer conserve la
    progression, car la cle est une empreinte du contenu, pas le chemin."""
    path = _make_manga(tmp_path, "avant.cbz", b"one-piece-tome-12-bytes")
    store.set_progress(path, 42, 200, False)

    new_path = tmp_path / "apres.cbz"
    (tmp_path / "avant.cbz").rename(new_path)

    assert store.get_progress(str(new_path)) == (42, 200, False)


def test_distinct_files_do_not_collide(store, tmp_path):
    a = _make_manga(tmp_path, "a.cbz", b"contenu-A-different")
    b = _make_manga(tmp_path, "b.cbz", b"contenu-B-different")
    store.set_progress(a, 1, 10, False)
    store.set_progress(b, 9, 10, True)
    assert store.get_progress(a) == (1, 10, False)
    assert store.get_progress(b) == (9, 10, True)


def test_legacy_path_keyed_progress_migrates(store, tmp_path):
    """Une progression heritee, indexee par chemin absolu, doit etre lue puis
    reindexee par empreinte de contenu au premier acces."""
    path = _make_manga(tmp_path, "legacy.cbz")
    # injecte une entree "ancienne facon" (cle = chemin)
    store.progress[path] = {"page": 7, "total": 20, "finished": False}

    assert store.get_progress(path) == (7, 20, False)
    # la cle chemin a disparu au profit d'une cle de contenu
    assert path not in store.progress
    key = store.key_for(path)
    assert key in store.progress
    assert key.startswith("c1:")


def test_reader_offset(store, tmp_path):
    path = _make_manga(tmp_path, "a.cbz")
    assert store.get_reader_offset(path) == 0
    store.set_reader_offset(path, 1)
    assert store.get_reader_offset(path) == 1
    # l'offset cohabite avec la progression dans la meme entree
    store.set_progress(path, 3, 50, False)
    assert store.get_reader_offset(path) == 1
    assert store.get_progress(path) == (3, 50, False)


def test_meta_cache_separate_file(store, tmp_path):
    path = _make_manga(tmp_path, "a.cbz")
    store.set_volume_meta(path, {"authors": ["Oda"], "published_year": 1997})
    store.set_series_meta("one piece", {"title": "One Piece"})
    store.flush()

    meta_file = storage.data_dir() / "meta_cache.json"
    settings_file = storage.data_dir() / "settings.json"
    assert meta_file.exists()
    data = json.loads(meta_file.read_text(encoding="utf-8"))
    assert "volume" in data and "series" in data
    # les caches ne polluent plus settings.json
    settings = json.loads(settings_file.read_text(encoding="utf-8")) if settings_file.exists() else {}
    assert "volume_meta_cache" not in settings
    assert "series_meta_cache" not in settings


def test_meta_cache_migrated_out_of_settings(tmp_path, monkeypatch):
    """Un settings.json ancien contenant les caches doit voir ceux-ci
    deplaces vers meta_cache.json au demarrage."""
    monkeypatch.setattr(storage, "data_dir", lambda: tmp_path / "MangaReaderPy")
    d = tmp_path / "MangaReaderPy"
    d.mkdir(parents=True)
    (d / "settings.json").write_text(json.dumps({
        "folders": [],
        "reader": {},
        "volume_meta_cache": {"c1:abc": {"authors": ["X"]}},
        "series_meta_cache": {"naruto": {"title": "Naruto"}},
    }), encoding="utf-8")

    s = Store()
    assert s.meta_cache["volume"] == {"c1:abc": {"authors": ["X"]}}
    assert s.meta_cache["series"] == {"naruto": {"title": "Naruto"}}
    assert "volume_meta_cache" not in s.settings
    s.flush()
    settings = json.loads((d / "settings.json").read_text(encoding="utf-8"))
    assert "volume_meta_cache" not in settings


def test_flush_persists_debounced_writes(store, tmp_path):
    path = _make_manga(tmp_path, "a.cbz")
    store.set_progress(path, 1, 10, False)
    store.flush()
    prog_file = storage.data_dir() / "progress.json"
    data = json.loads(prog_file.read_text(encoding="utf-8"))
    key = store.key_for(path)
    assert data[key]["page"] == 1
