"""Serveurs de lecture (infra/servers.py, services/servers.py) face a de
faux serveurs Komga, Kavita et OPDS locaux (tests/fake_servers.py)."""

import pytest

from beheread import platforms
from beheread.infra import servers
from beheread.infra.archive import Archive, ArchiveError
from beheread.infra.servers import ServerConfig, ServerError
from tests.fake_servers import API_KEY, KOMGA_PASSWORD, KOMGA_USER, FakeServers


@pytest.fixture
def fake():
    srv = FakeServers()
    yield srv
    srv.close()


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    servers.registry.set_clients({})


@pytest.fixture
def secrets(monkeypatch):
    """Secrets en memoire : ni DPAPI ni Trousseau pendant les tests."""
    vault = {}

    def protect(name, secret):
        vault[name] = secret
        return "test:" + name
    monkeypatch.setattr(platforms, "protect_secret", protect)
    monkeypatch.setattr(platforms, "unprotect_secret", lambda v: vault.get(v[5:]))
    monkeypatch.setattr(platforms, "discard_secret", lambda v: vault.pop(v[5:], None))
    return vault


def komga(fake, user=KOMGA_USER, secret=KOMGA_PASSWORD):
    return servers.make_client(ServerConfig("k1", "komga", "Komga", fake.url, user), secret)


def test_paths_identify_remote_volumes():
    path = servers.make_path("k1", "B12")
    assert path == "beheread-server:k1:B12" and servers.is_remote(path)
    assert servers.split_path(path) == ("k1", "B12")
    assert not servers.is_remote(r"C:\mangas\Berserk 1.cbz")
    # un identifiant OPDS (urn, adresse) devient une empreinte sans separateur
    odd = servers.safe_id("urn:uuid:1/2.3")
    assert odd.isalnum() and servers.safe_id("urn:uuid:1/2.3") == odd
    assert servers.display_name(r"C:\mangas\Berserk 1.cbz") == "Berserk 1"


def test_urls_are_normalized_and_checked():
    assert servers.normalize_url("192.168.1.20:25600/") == "http://192.168.1.20:25600"
    with pytest.raises(ServerError):
        servers.normalize_url("ftp://serveur")
    with pytest.raises(ServerError):
        servers.normalize_url("")


def test_komga_lists_books_page_by_page(fake):
    client = komga(fake)
    assert client.check() == {"version": "Komga 1.21.2", "count": 4}
    books = client.books()
    assert [b.title for b in books] == ["Berserk - Tome 1", "Berserk - Tome 2",
                                        "Berserk - Tome 3", "Pluto - Tome 9"]
    first, pluto = books[0], books[3]
    assert (first.series, first.number, first.pages, first.year) == ("Berserk", 1, 4, 1990)
    assert first.author == "Kentaro Miura"           # scenaristes d'abord
    assert first.progress is None and pluto.progress == (2, False)   # page 3 (1-based)


def test_komga_api_key_and_refused_credentials(fake):
    assert komga(fake, user="", secret="komga-key").check()["count"] == 4
    with pytest.raises(ServerError, match="Identifiants refusés"):
        komga(fake, secret="mauvais").check()


def test_remote_archive_streams_pages_and_uses_thumbnails(fake):
    client = komga(fake)
    books = client.books()
    servers.registry.set_clients({"k1": client})
    servers.registry.add_books(books)
    ar = Archive(books[0].path)
    assert len(ar) == 4
    assert ar.read_page(2)[:2] == b"\xff\xd8"
    assert not ar.read_image(0, max_height=300).isNull()
    paths = [p for m, p, _b in fake.requests if m == "GET"]
    assert "/api/v1/books/B1/pages/3" in paths and "/api/v1/books/B1/thumbnail" in paths
    ar.close()
    with pytest.raises(ArchiveError):
        ar.read_page(0)


def test_unknown_remote_volume_cannot_be_opened():
    with pytest.raises(ArchiveError):
        Archive(servers.make_path("absent", "B1"))


def test_komga_progress_is_sent(fake):
    client = komga(fake)
    book = client.books()[1]
    client.push_progress(book, 2, False)
    client.push_progress(book, 3, True)
    assert fake.bodies("PATCH", "/api/v1/books/B2/read-progress") == [
        {"page": 3, "completed": False}, {"page": 4, "completed": True}]


def test_opds_catalog_is_crawled_within_the_server(fake):
    client = servers.make_client(ServerConfig("o1", "opds", "OPDS", fake.url + "/opds"), "")
    assert client.check()["version"] == "Ma bibliothèque"
    books = {b.title: b for b in client.books()}
    # page suivante suivie, lien vers une autre adresse ignore
    assert "Pluto - Tome 2" in books
    assert not any("example.invalid" in p for _m, p, _b in fake.requests)
    # le flux le plus petit donne la serie ; le titre en donne une quand il le peut
    monster = [b for b in books.values() if b.series == "Monster"]
    assert sorted(b.number for b in monster) == [1, 2]
    pluto = books["Pluto - Tome 2"]
    assert (pluto.series, pluto.number, pluto.download.endswith("/file/99")) == ("Pluto", 2, True)
    one = next(b for b in monster if b.number == 1)
    assert one.pages == 4 and one.progress == (1, False) and one.author == "Naoki Urasawa"
    assert next(b for b in monster if b.number == 2).progress == (3, True)
    assert one.year == 2003
    servers.registry.set_clients({"o1": client})
    servers.registry.add_books(books.values())
    assert Archive(one.path).read_page(1)
    assert ("GET", "/img/m1/1?w=4000", None) in fake.requests


def test_opds_without_streaming_is_loaded_in_memory(fake):
    client = servers.make_client(ServerConfig("o1", "opds", "OPDS", fake.url + "/opds"), "")
    pluto = next(b for b in client.books() if b.title == "Pluto - Tome 2")
    servers.registry.set_clients({"o1": client})
    servers.registry.add_books([pluto])
    assert servers.registry.needs_download(pluto.path)
    servers.registry.download(pluto.path)
    assert not servers.registry.needs_download(pluto.path)
    ar = Archive(pluto.path)
    assert len(ar) == 3 and ar.read_page(0)[:2] == b"\xff\xd8"


def test_kavita_reads_its_feed_and_sends_progress(fake):
    config = ServerConfig("v1", "kavita", "Kavita", fake.url)
    with pytest.raises(ServerError, match="clé d'API"):
        servers.make_client(config, "").check()
    client = servers.make_client(config, API_KEY)
    assert client.check()["version"] == "Kavita"
    (book,) = client.books()
    assert (book.series, book.number, book.pages) == ("Berserk", 1, 5)
    assert book.ids == {"libraryId": 1, "seriesId": 1, "volumeId": 7, "chapterId": 12}
    client.push_progress(book, 3, False)
    client.push_progress(book, 4, True)
    assert fake.bodies("POST", "/api/Reader/progress") == [
        {"libraryId": 1, "seriesId": 1, "volumeId": 7, "chapterId": 12, "pageNum": 3},
        {"libraryId": 1, "seriesId": 1, "volumeId": 7, "chapterId": 12, "pageNum": 5}]
    # adresse OPDS complete collee depuis Kavita : la cle en est tiree
    pasted = ServerConfig("v2", "kavita", "Kavita", f"{fake.url}/api/opds/{API_KEY}")
    assert len(servers.make_client(pasted, "").books()) == 1


def test_redirect_to_another_address_is_refused(fake):
    fake.redirect_to = "http://example.invalid/vol"
    client = servers.make_client(ServerConfig("o1", "opds", "OPDS", fake.url + "/redirect"), "")
    with pytest.raises(ServerError, match="autre adresse"):
        client.check()


# ---------------------------------------------------------------- service

@pytest.fixture
def store(qapp, tmp_path, monkeypatch, secrets):
    from beheread.infra import storage
    monkeypatch.setattr(storage, "data_dir", lambda: tmp_path)
    s = storage.Store()
    yield s
    s.close()


def _manager(store, fake, enabled=True):
    from beheread.services.servers import ServerManager
    store.set_ui_pref("servers_enabled", enabled)
    store.save_server({"id": "k1", "kind": "komga", "name": "Komga (maison)", "url": fake.url,
                       "user": KOMGA_USER}, KOMGA_PASSWORD)
    return ServerManager(store)


def test_servers_are_off_by_default(store, fake):
    manager = _manager(store, fake, enabled=False)
    assert not manager.enabled() and servers.registry.client("k1") is None
    manager.fetch("k1")
    assert fake.requests == []


def test_secret_is_protected_and_kept_when_editing(store, secrets):
    store.save_server({"id": "k1", "kind": "komga", "name": "A", "url": "http://x", "user": "u"}, "pw")
    assert store.servers()[0]["secret_enc"] == "test:server-k1" and secrets["server-k1"] == "pw"
    store.save_server({"id": "k1", "kind": "komga", "name": "B", "url": "http://x", "user": "u"}, None)
    assert store.servers()[0]["name"] == "B" and store.server_secret("k1") == "pw"
    store.remove_server("k1")
    assert store.servers() == [] and "server-k1" not in secrets


def test_listing_merges_server_progress_and_session_end_sends_it(qtbot, store, fake):
    manager = _manager(store, fake)
    pluto = servers.make_path("k1", "B9")
    finished_here = servers.make_path("k1", "B1")
    store.set_progress(finished_here, 3, 4, True)
    with qtbot.waitSignal(manager.listed, timeout=5000) as blocker:
        manager.fetch("k1")
    assert blocker.args[0] == "k1" and len(blocker.args[1]) == 4
    assert store.get_progress(pluto)[:2] == (2, 4)                 # repris du serveur
    assert store.get_progress(finished_here) == (3, 4, True)       # jamais recule
    assert store.volume_meta(pluto) == {"source": "server", "authors": ["Kentaro Miura"],
                                        "published_year": 1990}
    store.set_progress(pluto, 3, 4, True)
    manager.on_session_end(pluto)
    qtbot.waitUntil(lambda: bool(fake.bodies("PATCH", "/api/v1/books/B9/read-progress")),
                    timeout=5000)
    assert fake.bodies("PATCH", "/api/v1/books/B9/read-progress") == [{"page": 4, "completed": True}]


def test_listing_error_is_reported(qtbot, store, fake):
    manager = _manager(store, fake)
    store.save_server({"id": "k1", "kind": "komga", "name": "Komga", "url": fake.url,
                       "user": KOMGA_USER}, "mauvais")
    manager.reload()
    with qtbot.waitSignal(manager.listed, timeout=5000) as blocker:
        manager.fetch("k1")
    assert blocker.args[1] is None and "Identifiants" in manager.error("k1")
