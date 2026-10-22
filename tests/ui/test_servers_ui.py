"""Serveurs de lecture dans l'interface : onglet des preferences, ajout d'un
serveur, choix de la source dans l'en-tete et lecture d'un tome distant
(faux serveur Komga local, voir tests/fake_servers.py)."""

import pytest
from PySide6.QtCore import QThreadPool

from beheread import platforms
from beheread.infra import servers
from beheread.ui import theme
from beheread.ui.library.dialogs import PreferencesDialog
from beheread.ui.library.servers_ui import ServerDialog
from tests.fake_servers import KOMGA_PASSWORD, KOMGA_USER, FakeServers


@pytest.fixture
def fake():
    srv = FakeServers()
    yield srv
    srv.close()


@pytest.fixture(autouse=True)
def _secrets(monkeypatch):
    vault = {}

    def protect(name, secret):
        vault[name] = secret
        return "test:" + name
    monkeypatch.setattr(platforms, "protect_secret", protect)
    monkeypatch.setattr(platforms, "unprotect_secret", lambda v: vault.get(v[5:]))
    monkeypatch.setattr(platforms, "discard_secret", lambda v: vault.pop(v[5:], None))
    yield
    servers.registry.set_clients({})


def _add_komga(store, fake):
    store.save_server({"id": "k1", "kind": "komga", "name": "Komga (maison)", "url": fake.url,
                       "user": KOMGA_USER}, KOMGA_PASSWORD)


def test_servers_tab_is_off_by_default(qtbot, store):
    dlg = PreferencesDialog(store, theme.colors("dark"), {})
    qtbot.addWidget(dlg)
    assert not dlg.servers_enabled.isChecked()
    assert not dlg.server_add.isEnabled() and not dlg.server_list.isEnabled()
    dlg.servers_enabled.setChecked(True)
    assert dlg.server_add.isEnabled() and dlg.servers_sync.isChecked()
    dlg.save()
    assert store.ui_pref("servers_enabled") is True


def test_server_dialog_tests_the_connection_and_saves(qtbot, store, fake):
    dlg = ServerDialog(store)
    qtbot.addWidget(dlg)
    dlg.kind.setCurrentIndex(dlg.kind.findData("komga"))
    dlg.name.setText("Komga (maison)")
    dlg.url.setText(fake.url)
    dlg.user.setText(KOMGA_USER)
    dlg.secret.setText(KOMGA_PASSWORD)
    dlg._test()
    qtbot.waitUntil(lambda: "réussie" in dlg.result.text(), timeout=5000)
    assert dlg.result.text() == "✓ Connexion réussie · Komga 1.21.2 · 4 tomes"
    dlg._accept()
    (saved,) = store.servers()
    assert (saved["name"], saved["url"], saved["user"]) == ("Komga (maison)", fake.url, KOMGA_USER)
    assert store.server_secret(saved["id"]) == KOMGA_PASSWORD

    # Kavita n'a pas d'identifiant ; une adresse inutilisable est signalee
    dlg = ServerDialog(store)
    qtbot.addWidget(dlg)
    dlg.kind.setCurrentIndex(dlg.kind.findData("kavita"))
    assert not dlg.user.isEnabled()
    dlg.url.setText("ftp://nulle-part")
    dlg._test()
    assert "Adresse non reconnue" in dlg.result.text()


@pytest.fixture
def remote_window(qtbot, store, fake):
    from beheread.app import MainWindow
    store.set_ui_pref("servers_enabled", True)
    _add_komga(store, fake)
    win = MainWindow(store)
    qtbot.addWidget(win)
    win.resize(1300, 850)
    win.show()
    yield win
    if win.reader is not None:
        win.reader.release()
    QThreadPool.globalInstance().waitForDone(5000)
    win.servers.pool.waitForDone(5000)


def test_library_shows_and_reads_a_server(qtbot, remote_window, fake, store):
    lib = remote_window.library
    assert lib.source_switch.isVisible()
    assert [b.text() for b in lib._source_buttons.values()] == ["Sur cet ordinateur",
                                                                "Komga (maison)"]
    lib.select_source("k1")
    qtbot.waitUntil(lambda: len(lib._entries) == 4, timeout=5000)
    assert store.ui_pref("library_source") == "k1"
    assert "sans copie sur le disque" in lib.count_label.text()
    first = servers.make_path("k1", "B1")
    assert lib.entry(first).series == "Berserk"
    assert lib.next_volume(first) == servers.make_path("k1", "B2")
    assert lib._server_name(first) == "Komga (maison)"
    lib._delete_many([first])          # jamais de suppression d'un tome distant

    remote_window.open_manga(first)
    reader = remote_window.reader
    assert reader is not None and reader.total == 4
    qtbot.waitUntil(lambda: 0 in reader.cache and not reader.cache[0].isNull(), timeout=5000)
    reader.next_page(animate=False)
    reader.close_reader()
    qtbot.waitUntil(lambda: bool(fake.bodies("PATCH", "/api/v1/books/B1/read-progress")),
                    timeout=5000)

    lib.select_source("local")
    assert lib._entries == [] and not lib.is_remote_source()


def test_disabling_servers_returns_to_local(qtbot, remote_window, store):
    lib = remote_window.library
    lib.select_source("k1")
    store.set_ui_pref("servers_enabled", False)
    remote_window.servers.reload()
    assert not lib.source_switch.isVisible() and not lib.is_remote_source()


def test_server_chapters_are_told_apart_from_volumes(window, qtbot):
    """Livres d'un serveur : « Chapitre 211 » dans le titre en fait un
    chapitre, qui complete les tomes comme en local."""
    from beheread.core import units
    books = [servers.RemoteBook("k9", "V1", "Chainsaw Man T01", "Chainsaw Man", 1, pages=4),
             servers.RemoteBook("k9", "V2", "Chainsaw Man T02", "Chainsaw Man", 2, pages=4),
             servers.RemoteBook("k9", "C1", "Chainsaw Man Chapitre 211", "Chainsaw Man", 211,
                                pages=4)]
    lib = window.library
    lib._apply_remote_books(books)
    kinds = {e.title: e.kind for e in lib._entries}
    assert kinds == {"Chainsaw Man T01": "volume", "Chainsaw Man T02": "volume",
                     "Chainsaw Man Chapitre 211": "chapter"}
    chapter = lib.entry(servers.make_path("k9", "C1"))
    assert lib._unit(chapter) == units.CHAPTER
    assert lib.next_volume(servers.make_path("k9", "V2")) == chapter.path
