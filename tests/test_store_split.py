"""Tests de la separation bibliotheque / profil (storage.py) : LibraryStore et
ProfileStore chacune sur sa propre base (usage d'un serveur Beheread), et
reprise par les deux des donnees d'une base du desktop (Store)."""

import pytest

from beheread.infra import storage
from beheread.infra.storage import LibraryStore, ProfileStore, Store


@pytest.fixture
def desktop_dir(tmp_path, monkeypatch):
    folder = tmp_path / "MangaReaderPy"
    folder.mkdir()
    monkeypatch.setattr(storage, "data_dir", lambda: folder)
    return folder


def _volume(tmp_path, name="Berserk 01.cbz", content=b"PK\x03\x04 tome"):
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


def test_every_repository_belongs_to_one_side():
    library, profile = LibraryStore.REPO_NAMES, ProfileStore.REPO_NAMES
    assert library | profile == set(storage.REPOS)
    assert library & profile == {"settings"}   # chacun ses lignes de reglages
    assert Store.REPO_NAMES == library | profile


def test_library_store_alone(tmp_path):
    base = tmp_path / "serveur"
    volume = _volume(tmp_path)
    lib = LibraryStore(base, "bibliotheque.db")
    key = lib.key_for(volume)
    assert key.startswith("c1:")
    lib.set_page_count(volume, 180)
    lib.set_series_name("berserk", "Berserk (édition Deluxe)")
    lib.close()

    again = LibraryStore(base, "bibliotheque.db")
    assert again.page_count(volume) == 180
    assert again.series_name("berserk") == "Berserk (édition Deluxe)"
    assert not hasattr(again, "progress")
    again.close()


def test_profile_store_alone_uses_fingerprints(tmp_path):
    base = tmp_path / "serveur"
    key = "c1:" + "0" * 40   # un serveur recoit des empreintes, pas des chemins
    profile = ProfileStore(base, "profil-lea.db")
    profile.set_progress(key, 86, 212, False)
    profile.dismiss_continue(key)
    profile.record_reading(key, pages=12, seconds=300, finished=False,
                           title="Berserk 14", series="Berserk")
    profile.close()

    again = ProfileStore(base, "profil-lea.db")
    assert again.get_progress(key) == (86, 212, False)
    assert key in again.continue_dismissed()
    assert again.reading_log.export()   # la seance est au journal
    assert not hasattr(again, "meta_cache")
    again.close()


def test_profiles_are_independent(tmp_path):
    base = tmp_path / "serveur"
    key = "c1:" + "1" * 40
    lea, hugo = ProfileStore(base, "profil-lea.db"), ProfileStore(base, "profil-hugo.db")
    lea.set_progress(key, 40, 200, False)
    lea.flush()
    assert hugo.get_progress(key) is None
    lea.close()
    hugo.close()


def test_desktop_database_read_by_both_sides(desktop_dir, tmp_path):
    # amorcage d'un serveur : la base du desktop se lit cote bibliotheque et
    # cote profil, sans rien perdre
    volume = _volume(tmp_path)
    store = Store()
    store.set_progress(volume, 87, 212, False)
    store.set_series_name("berserk", "Berserk")
    store.set_ui_pref("theme", "dark")
    key = store.key_for(volume)
    store.close()

    lib = LibraryStore(desktop_dir)
    assert lib.key_for(volume) == key
    assert lib.series_name("berserk") == "Berserk"
    lib.close()
    profile = ProfileStore(desktop_dir)
    assert profile.get_progress(key) == (87, 212, False)
    assert profile.ui_pref("theme") == "dark"
    profile.close()
