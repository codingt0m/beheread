"""Tests des controleurs de la bibliotheque (scan, metadonnees, couvertures),
extraits de LibraryWidget. Reseau simule : aucune requete reelle."""

from PySide6.QtWidgets import QListWidgetItem

from beheread.core.models import LibraryEntry
from beheread.infra import metadata
from beheread.ui.library.constants import ROLE_PIXMAP
from beheread.ui.library.controllers import (
    CoverCache,
    MetadataController,
    ScanController,
)
from tests.ui.conftest import make_cbz


def test_scan_controller_scans_and_coalesces(qtbot, store, mangas):
    make_cbz(mangas, "Alpha - Tome 1", seed=1)
    make_cbz(mangas, "Alpha - Tome 2", seed=2)
    store.set_folders([str(mangas)])
    scanner = ScanController(store)
    results = []
    scanner.scanned.connect(lambda paths, cloud, _local: results.append((sorted(paths), cloud)))
    scanner.refresh()
    scanner.refresh()          # demande pendant le scan : relance a la fin, pas en double
    qtbot.waitUntil(lambda: len(results) == 2 and not scanner.scanning, timeout=10000)
    assert len(results[0][0]) == 2 and results[0][1] == []
    assert str(mangas) in scanner._watcher.directories()   # surveillance installee


def test_metadata_controller_fetches_once_and_caches(qtbot, store, mangas, monkeypatch):
    path = make_cbz(mangas, "Berserk - Tome 1", seed=1)
    calls = {"volume": 0, "series": 0}

    def fake_fetch(p, series, volume, cached_series, online=True, author_hint=None):
        calls["volume"] += 1
        assert online is True
        return {"authors": ["Kentaro Miura"], "published_year": 1990, "source": "googlebooks"}, True, None

    def fake_series(name, hint=None):
        calls["series"] += 1
        return {"authors": ["Kentaro Miura"], "published_year": 1989, "source": "anilist"}, True

    monkeypatch.setattr(metadata, "fetch", fake_fetch)
    monkeypatch.setattr(metadata, "fetch_series", fake_series)
    ctrl = MetadataController(store, online=lambda: True)
    updated, series_updated = [], []
    ctrl.volumeUpdated.connect(updated.append)
    ctrl.seriesUpdated.connect(series_updated.append)
    entry = LibraryEntry(path=path, title="Berserk - Tome 1", series="Berserk", volume=1)

    assert ctrl.cached_or_fetch(entry) is None        # pas encore connu : recherche lancee
    qtbot.waitUntil(lambda: bool(updated and series_updated), timeout=10000)
    assert store.volume_meta(path)["authors"] == ["Kentaro Miura"]
    assert store.series_meta("berserk")["published_year"] == 1989
    assert ctrl.cached_or_fetch(entry)["source"] == "googlebooks"   # depuis le cache
    assert calls == {"volume": 1, "series": 1}


def test_metadata_controller_offline_never_searches_series(qtbot, store, mangas, monkeypatch):
    path = make_cbz(mangas, "Berserk - Tome 1", seed=1)
    seen = []
    monkeypatch.setattr(metadata, "fetch",
                        lambda p, s, v, c, online=True, author_hint=None: (seen.append(online), (None, False, None))[1])
    monkeypatch.setattr(metadata, "fetch_series",
                        lambda name, hint=None: (_ for _ in ()).throw(AssertionError("reseau interdit")))
    ctrl = MetadataController(store, online=lambda: False)
    done = []
    ctrl.volumeUpdated.connect(done.append)
    ctrl.cached_or_fetch(LibraryEntry(path=path, title="t", series="Berserk", volume=1))
    qtbot.waitUntil(lambda: bool(done), timeout=10000)
    assert seen == [False] and store.volume_meta(path) is None   # rien de mis en cache
    # echec memorise : pas de nouvelle tentative avant forget_failures
    ctrl.cached_or_fetch(LibraryEntry(path=path, title="t", series="Berserk", volume=1))
    assert len(seen) == 1
    ctrl.forget_failures()
    ctrl.cached_or_fetch(LibraryEntry(path=path, title="t", series="Berserk", volume=1))
    qtbot.waitUntil(lambda: len(seen) == 2, timeout=10000)


def test_cover_cache_serves_subscribed_items(qtbot, store, mangas):
    from PySide6.QtCore import QSize
    path = make_cbz(mangas, "Alpha - Tome 1", seed=1)
    covers = CoverCache(store, QSize(100, 141))
    item = QListWidgetItem("a")
    ready = []
    covers.coverReady.connect(ready.append)
    covers.bind(item, path, ROLE_PIXMAP)
    qtbot.waitUntil(lambda: ready == [path], timeout=10000)
    pm = item.data(ROLE_PIXMAP)
    assert pm is not None and (pm.width(), pm.height()) == (100, 141)
    assert store.thumb_path(path).exists()            # cache disque ecrit
    assert store.page_count(path) == 4                # nombre de pages memorise
    other = QListWidgetItem("b")
    covers.bind(other, path, ROLE_PIXMAP)             # deja en memoire : immediat
    assert other.data(ROLE_PIXMAP) is not None
    covers.rename(path, path + ".x")
    assert covers.get(path + ".x") is not None and covers.get(path) is None


def test_metadata_controller_refreshes_stale_results(qtbot, store, mangas, monkeypatch):
    """Un resultat AniList ecrit par une cascade plus ancienne reste affiche
    pendant qu'il est recherche de nouveau, puis il est remplace."""
    path = make_cbz(mangas, "Monster - Tome 6", seed=1)
    store.set_volume_meta(path, {"authors": ["Hatch"], "source": "anilist"})   # perime
    store.set_series_meta("monster", {"not_found": True, "cascade_version": 1})

    def fake_fetch(p, series, volume, cached_series, online=True, author_hint=None):
        assert cached_series is None   # « introuvable » perime : pas reutilise
        return ({"authors": ["Naoki Urasawa"], "source": "anilist",
                 "cascade_version": metadata.CASCADE_VERSION}, True, None)

    monkeypatch.setattr(metadata, "fetch", fake_fetch)
    monkeypatch.setattr(metadata, "fetch_series", lambda name, hint=None: (metadata.not_found_sentinel(), True))
    ctrl = MetadataController(store, online=lambda: True)
    updated = []
    ctrl.volumeUpdated.connect(updated.append)
    entry = LibraryEntry(path=path, title="Monster - Tome 6", series="Monster", volume=6)

    assert ctrl.cached_or_fetch(entry)["authors"] == ["Hatch"]   # affiche en attendant
    qtbot.waitUntil(lambda: bool(updated), timeout=10000)
    assert ctrl.cached_or_fetch(entry)["authors"] == ["Naoki Urasawa"]



def test_provisional_result_is_not_retried_in_the_same_session(qtbot, store, mangas,
                                                               monkeypatch):
    """Un resultat provisoire (AniList injoignable) est affiche, sans
    nouvelle tentative avant la session suivante."""
    path = make_cbz(mangas, "Vagabond - Tome 1", seed=1)
    calls = []

    def fake_fetch(p, series, volume, cached_series, online=True, author_hint=None):
        calls.append(p)
        data = {"authors": ["Inoue"], "source": "mangadex", "partial": True,
                "cascade_version": metadata.CASCADE_VERSION}
        return data, True, data

    monkeypatch.setattr(metadata, "fetch", fake_fetch)
    monkeypatch.setattr(metadata, "fetch_series", lambda name, hint=None: (None, False))
    ctrl = MetadataController(store, online=lambda: True)
    updated = []
    ctrl.volumeUpdated.connect(updated.append)
    entry = LibraryEntry(path=path, title="Vagabond - Tome 1", series="Vagabond", volume=1)
    ctrl.cached_or_fetch(entry)
    qtbot.waitUntil(lambda: bool(updated), timeout=10000)
    assert ctrl.cached_or_fetch(entry)["authors"] == ["Inoue"]
    qtbot.wait(100)
    assert calls == [path]
