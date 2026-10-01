"""Tests de la persistance (storage.py) : identite par contenu, migration des
entrees indexees par chemin, decalage de parite, decoupage de settings.json.

`data_dir()` s'appuie sur %APPDATA% ; chaque test le redirige vers un dossier
temporaire isole.
"""

import json

import pytest

from beheread.infra import storage
from beheread.infra.storage import Store


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    # hors Windows, data_dir() ignore APPDATA : on force le dossier de donnees
    monkeypatch.setattr(storage, "data_dir", lambda: tmp_path / "MangaReaderPy")
    (tmp_path / "MangaReaderPy").mkdir(parents=True, exist_ok=True)
    return Store()


def _reopen(store):
    """Nouveau Store sur le meme dossier : ce qui a ete reellement persiste."""
    store.flush()
    return Store()


def _db_row(store, table, key):
    """Valeur telle qu'enregistree dans la base (connexion independante)."""
    import sqlite3
    con = sqlite3.connect(str(store.dir / storage.DB_NAME))
    try:
        row = con.execute(f"SELECT value FROM {table} WHERE key = ?", (key,)).fetchone()
    finally:
        con.close()
    return json.loads(row[0]) if row else None


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


def test_key_for_cloud_placeholder_never_reads_content(store, tmp_path, monkeypatch):
    """Un fichier cloud non telecharge (iCloud/OneDrive) ne doit JAMAIS etre
    lu : la moindre lecture declencherait son telechargement complet et
    bloquant. key_for doit se replier sur le chemin sans ouvrir le fichier."""
    path = _make_manga(tmp_path, "cloud.cbz")
    monkeypatch.setattr(storage, "is_cloud_placeholder", lambda p: True)

    def _forbidden(p):
        raise AssertionError("le contenu d'un espace reserve cloud a ete lu")
    monkeypatch.setattr(storage, "_compute_fingerprint", _forbidden)

    assert store.key_for(path) == path
    # le repli n'est pas memorise : une fois le fichier en local, l'empreinte
    # reelle doit etre calculee
    assert path not in store._fp


def test_placeholder_progress_migrates_once_downloaded(store, tmp_path, monkeypatch):
    """La progression enregistree pendant que le fichier etait un espace
    reserve cloud (cle = chemin) doit etre retrouvee et reindexee par contenu
    une fois le fichier telecharge en local (meme mecanisme que la migration
    des entrees heritees)."""
    path = _make_manga(tmp_path, "cloud.cbz")
    monkeypatch.setattr(storage, "is_cloud_placeholder", lambda p: True)
    store.set_progress(path, 3, 10, False)
    assert path in store.progress   # indexee par chemin tant que non local

    monkeypatch.setattr(storage, "is_cloud_placeholder", lambda p: False)
    assert store.get_progress(path) == (3, 10, False)
    assert path not in store.progress
    assert store.key_for(path).startswith("c1:")


def test_is_cloud_placeholder_false_for_regular_file(store, tmp_path):
    """Un fichier ordinaire present sur le disque n'est pas un espace reserve
    (et un chemin inexistant non plus : pas de faux positif bloquant)."""
    path = _make_manga(tmp_path, "local.cbz")
    assert storage.is_cloud_placeholder(path) is False
    assert storage.is_cloud_placeholder(str(tmp_path / "absent.cbz")) is False


def test_meta_cache_separate_file(store, tmp_path):
    """Les metadonnees ont leurs propres depots : elles ne polluent pas les
    reglages, et survivent a une reouverture."""
    path = _make_manga(tmp_path, "a.cbz")
    store.set_volume_meta(path, {"authors": ["Oda"], "published_year": 1997})
    store.set_series_meta("one piece", {"title": "One Piece"})
    store.flush()

    again = _reopen(store)
    assert again.volume_meta(path)["authors"] == ["Oda"]
    assert again.series_meta("one piece") == {"title": "One Piece"}
    assert "volume_meta_cache" not in again.settings
    assert "series_meta_cache" not in again.settings


def test_meta_cache_migrated_out_of_settings(tmp_path, monkeypatch):
    """Un settings.json ancien contenant les caches doit voir ceux-ci
    deplaces vers les depots de metadonnees au demarrage."""
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
    again = _reopen(s)
    assert "volume_meta_cache" not in again.settings
    assert again.meta_cache["series"] == {"naruto": {"title": "Naruto"}}


def test_flush_persists_debounced_writes(store, tmp_path):
    path = _make_manga(tmp_path, "a.cbz")
    store.set_progress(path, 1, 10, False)
    store.flush()
    assert _db_row(store, "progress", store.key_for(path))["page"] == 1


def test_purge_orphan_caches_removes_stale_thumbnail(store, tmp_path):
    """Purge une vignette dont le fichier source a disparu, et conserve celle
    d'un fichier toujours present."""
    kept = _make_manga(tmp_path, "kept.cbz", b"kept-content")
    gone = _make_manga(tmp_path, "gone.cbz", b"gone-content")
    kept_thumb = store.thumb_path(kept)
    gone_thumb = store.thumb_path(gone)
    kept_thumb.write_bytes(b"jpeg")
    gone_thumb.write_bytes(b"jpeg")

    store.purge_orphan_caches([kept])

    assert kept_thumb.exists()
    assert not gone_thumb.exists()


def test_purge_orphan_caches_drops_stale_fingerprint(store, tmp_path):
    """L'empreinte indexee par chemin d'un fichier disparu est retiree."""
    kept = _make_manga(tmp_path, "kept.cbz", b"kept-content")
    gone = _make_manga(tmp_path, "gone.cbz", b"gone-content")
    store.key_for(kept)   # renseigne le cache d'empreintes
    store.key_for(gone)
    assert gone in store._fp

    store.purge_orphan_caches([kept])

    assert gone not in store._fp
    assert kept in store._fp


def test_purge_orphan_caches_keeps_progress(store, tmp_path):
    """Garde-fou : la progression (indexee par contenu) n'est jamais purgee,
    meme pour un fichier absent du scan (disque reseau deconnecte)."""
    gone = _make_manga(tmp_path, "gone.cbz", b"gone-content")
    store.set_progress(gone, 3, 10, False)
    key = store.key_for(gone)

    store.purge_orphan_caches([])   # aucun fichier present

    assert store.progress.get(key, {}).get("page") == 3


# ---------------------------------------------------------------- suppression

def test_forget_content_after_delete(store, tmp_path):
    """Apres une suppression reussie, progression, date d'ajout et metadonnees
    du tome sont oubliees (cle resolue AVANT la suppression du fichier)."""
    path = _make_manga(tmp_path, "a.cbz")
    store.set_progress(path, 4, 10, False)
    store.ensure_added([path])
    store.set_volume_meta(path, {"authors": ["X"]})
    key = store.key_for(path)

    (tmp_path / "a.cbz").unlink()
    store.forget_content(key, path)

    assert key not in store.progress
    assert key not in store.settings["added"]
    assert key not in store.meta_cache["volume"]
    assert path not in store._fp


def test_forget_content_keeps_data_shared_by_identical_copy(store, tmp_path):
    """Supprimer une copie ne doit pas effacer la progression partagee par
    contenu avec une autre copie identique toujours presente."""
    a = _make_manga(tmp_path, "a.cbz", b"meme-contenu")
    b = _make_manga(tmp_path, "b.cbz", b"meme-contenu")
    store.set_progress(a, 4, 10, False)
    key = store.key_for(a)
    assert store.key_for(b) == key

    (tmp_path / "a.cbz").unlink()
    store.forget_content(key, a)

    assert store.get_progress(b) == (4, 10, False)


# ---------------------------------------------------------------- empreintes memorisees

def test_key_for_is_memoized_until_invalidated(store, tmp_path, monkeypatch):
    """Une fois resolue, l'empreinte d'un chemin ne refait plus d'os.stat
    (appele plusieurs fois par item sur le thread UI) jusqu'au scan suivant."""
    path = _make_manga(tmp_path, "a.cbz")
    key = store.key_for(path)

    calls = []
    real_stat = storage.os.stat
    monkeypatch.setattr(storage.os, "stat", lambda p, *a, **k: calls.append(p) or real_stat(p, *a, **k))
    assert store.key_for(path) == key
    assert calls == []

    store.invalidate_key_memo()
    assert store.key_for(path) == key
    assert calls   # revalidation (mtime+taille) apres invalidation


def test_key_for_detects_modified_file_after_invalidation(store, tmp_path):
    path = _make_manga(tmp_path, "a.cbz", b"version-1")
    k1 = store.key_for(path)
    _make_manga(tmp_path, "a.cbz", b"version-2-plus-longue")
    store.invalidate_key_memo()
    assert store.key_for(path) != k1


# ---------------------------------------------------------------- ecritures differees

def test_concurrent_modification_during_serialization_is_retried(store, tmp_path, monkeypatch):
    """Si un dict est modifie par un autre thread pendant la serialisation
    (RuntimeError), la sauvegarde est remise en attente au lieu d'etre perdue."""
    from beheread.infra import database
    path = _make_manga(tmp_path, "a.cbz")
    store.set_progress(path, 2, 10, False)

    real_dumps = database.json.dumps
    state = {"failed": False}

    def flaky_dumps(obj, *a, **k):
        if not state["failed"]:
            state["failed"] = True
            raise RuntimeError("dictionary changed size during iteration")
        return real_dumps(obj, *a, **k)

    monkeypatch.setattr(database.json, "dumps", flaky_dumps)
    with store._save_lock:
        store._dirty = {"progress"}
    assert store._flush() is False
    assert "progress" in store._dirty   # toujours en attente, pas abandonne

    store.flush()
    assert _db_row(store, "progress", store.key_for(path))["page"] == 2


def test_debounced_write_happens_without_explicit_flush(store, tmp_path, monkeypatch):
    """Le thread de sauvegarde ecrit de lui-meme apres le delai d'inactivite."""
    import time
    monkeypatch.setattr(storage, "SAVE_DELAY", 0.05)
    path = _make_manga(tmp_path, "a.cbz")
    store.set_progress(path, 5, 10, False)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = _db_row(store, "progress", store.key_for(path))
        if row and row.get("page") == 5:
            break
        time.sleep(0.02)
    else:
        pytest.fail("la sauvegarde differee n'a jamais ete ecrite")


# ---------------------------------------------------------------- lot 3

def test_series_name_override(store):
    assert store.series_name("berserk") is None
    store.set_series_name("berserk", "Berserk (édition prestige)")
    assert store.series_name("berserk") == "Berserk (édition prestige)"
    store.set_series_name("berserk", "")
    assert store.series_name("berserk") is None


def test_dismiss_continue_is_keyed_by_content(store, tmp_path):
    path = _make_manga(tmp_path, "a.cbz")
    store.dismiss_continue(path)
    assert store.key_for(path) in store.continue_dismissed()


def test_clear_downloaded_meta_keeps_local_and_manual(store, tmp_path):
    a = _make_manga(tmp_path, "a.cbz", b"a")
    b = _make_manga(tmp_path, "b.cbz", b"b")
    c = _make_manga(tmp_path, "c.cbz", b"c")
    store.set_volume_meta(a, {"authors": ["X"], "source": "googlebooks"})
    store.set_volume_meta(b, {"authors": ["Y"], "source": "manual"})
    store.set_volume_meta(c, {"not_found": True})
    store.set_series_meta("s1", {"authors": ["Z"], "source": "anilist"})
    store.set_series_meta("s2", {"authors": ["W"], "source": "comicinfo"})

    assert store.clear_downloaded_meta() == 3
    assert store.volume_meta(a) is None and store.volume_meta(c) is None
    assert store.volume_meta(b)["source"] == "manual"
    assert store.series_meta("s1") is None and store.series_meta("s2") is not None


def test_clear_thumbnails(store, tmp_path):
    path = _make_manga(tmp_path, "a.cbz")
    store.thumb_path(path).write_bytes(b"jpeg")
    assert store.clear_thumbnails() == 1
    assert not store.thumb_path(path).exists()


# ---------------------------------------------------------------- lot 5

def test_reset_progress_removes_entry(store, tmp_path):
    """Reinitialiser efface l'entree (un import de sauvegarde peut donc la
    restaurer)."""
    path = _make_manga(tmp_path, "a.cbz")
    store.set_progress(path, 5, 10, False)
    store.remove_progress(path)
    assert store.get_progress(path) is None
    assert store.progress_ts(path) == 0.0
    assert store.key_for(path) not in store.progress


def test_record_reading_goes_to_this_device(store, tmp_path):
    import datetime
    path = _make_manga(tmp_path, "a.cbz")
    day = datetime.date(2026, 9, 27)
    store.record_reading(path, 12, 300, False, "A - Tome 1", "A", date=day)
    store.record_reading(path, 0, 0, False, "A - Tome 1", "A")   # session vide ignoree
    dev = store.reading_log.export()["devices"][store.device_id()]
    assert list(dev["days"]) == ["2026-09-27"] and dev["name"] == store.device_name()
    rec = dev["days"]["2026-09-27"][store.key_for(path)]
    assert rec["pages"] == 12 and rec["series"] == "A" and rec["sessions"] == 1
    # ecrit sur-le-champ : un autre Store sur la meme base le voit sans flush
    assert Store().reading_log.totals(day, day).pages == 12
    store.close()
    store.record_reading(path, 5, 60, False, "A - Tome 1", "A", date=day)   # base fermee : ignore


def test_finished_volumes_older_than_the_journal_are_imported_once(store, tmp_path):
    """Les tomes termines avant le premier jour du journal y sont inscrits (a
    la date de leur derniere lecture) ; ceux marques termines depuis, sans
    lecture enregistree, ne comptent pas."""
    import datetime
    import time
    old, recent = _make_manga(tmp_path, "a.cbz", b"a"), _make_manga(tmp_path, "b.cbz", b"b")
    reading = _make_manga(tmp_path, "c.cbz", b"c")
    journal_start = datetime.date.today() - datetime.timedelta(days=10)
    store.set_progress(old, 9, 10, True)
    long_ago = datetime.date.today() - datetime.timedelta(days=40)
    store.progress[store.key_for(old)]["ts"] = time.mktime(long_ago.timetuple()) + 43200
    store.set_progress(recent, 9, 10, True)                  # « Marquer comme lu » d'aujourd'hui
    store.record_reading(reading, 5, 100, False, "C", "C", date=journal_start)
    store.flush()
    with store.db.transaction() as cur:                      # base d'avant cette reprise
        cur.execute("DELETE FROM app_meta WHERE key = ?", (storage.FINISHED_HISTORY_KEY,))

    again = Store()
    everything = again.reading_log.totals("0000-01-01", "9999-12-31")
    assert everything.finished == 1 and everything.pages == 5
    assert again.reading_log.first_day() == long_ago
    assert Store().reading_log.totals("0000-01-01", "9999-12-31").finished == 1   # une seule fois


def test_reading_pace_is_remeasured_under_the_new_rules(store):
    """L'ancien rythme (intervalle entre tours de page, feuilletage compris)
    est oublie ; le nouveau est une moyenne lissee de secondes par page."""
    store.set_reader_pref("median_page_seconds", 0.486)
    assert _reopen(store).median_page_seconds() is None
    fresh = Store()
    assert "median_page_seconds" not in fresh.settings["reader"]
    fresh.update_page_seconds(10.0)
    fresh.update_page_seconds(20.0)
    assert fresh.median_page_seconds() == 13.0


def test_backup_export_import_roundtrip(tmp_path, monkeypatch):
    """Export sur un « PC », import sur un autre : la progression la plus
    recente est reprise, les reglages locaux ne sont pas ecrases."""
    manga = _make_manga(tmp_path, "a.cbz")

    def make_store(name):
        d = tmp_path / name
        d.mkdir()
        monkeypatch.setattr(storage, "data_dir", lambda d=d: d)
        return Store()

    pc1 = make_store("pc1")
    pc1.set_progress(manga, 7, 10, False)
    pc1.set_series_name("a", "Série A")
    pc1.record_reading(manga, 7, 210, False, "A", "A")
    backup = tmp_path / "sauvegarde.json"
    pc1.export_backup(backup)

    pc2 = make_store("pc2")
    pc2.set_series_name("a", "Nom local")
    pc2.record_reading(manga, 2, 30, False, "A", "A")
    result = pc2.import_backup(backup)
    assert result["progress"] == 1
    assert pc2.get_progress(manga) == (7, 10, False)
    assert pc2.series_name("a") == "Nom local"
    # journal de lecture : les deux PC s'additionnent, un second import ne double rien
    pc2.import_backup(backup)
    assert pc2.reading_log.totals("0000-01-01", "9999-12-31").pages == 9
    assert set(pc2.reading_log.devices()) == {pc1.device_id(), pc2.device_id()}

    # une progression reinitialisee par erreur est restauree par l'import
    pc2.remove_progress(manga)
    assert pc2.import_backup(backup)["progress"] == 1
    assert pc2.get_progress(manga) == (7, 10, False)

    bogus = tmp_path / "autre.json"
    bogus.write_text('{"hello": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        pc2.import_backup(bogus)


def test_anilist_token_is_never_stored_in_clear(store):
    store.set_anilist_login("super-secret-token", "tom")
    assert "super-secret-token" not in json.dumps(store.settings)
    assert store.anilist_token() == "super-secret-token"
    store.set_anilist_login(None, None)
    assert store.anilist_token() is None
