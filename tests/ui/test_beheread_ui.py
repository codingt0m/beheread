"""Serveur Beheread dans l'interface (maquettes validees) : bandeau de
reprise du lecteur, indicateur du serveur et provenance des tomes,
« Ajouter un appareil » et « Mettez Beheread a jour »."""

import time

from PySide6.QtWidgets import QApplication, QLabel

from beheread.infra.servers import ServerConfig, UpdateRequired
from beheread.ui.library.constants import ROLE_PATH, ROLE_WHERE, WHERE_LOCAL
from tests.ui.conftest import make_cbz


def test_reader_resumes_a_reading_from_another_device(window, qtbot, mangas, store):
    path = make_cbz(mangas, "Berserk T01", pages=6)
    key = store.key_for(path)
    store.apply_remote_progress(key, 3, 6, False, time.time() - 300, "ipad", before=1)
    window.open_manga(path)
    reader = window.reader
    assert reader.page == 3   # deja a la page lue sur l'autre appareil
    assert reader.resume_banner.isVisible()
    assert "page 4" in reader._resume_text.text()
    assert reader._resume_back.text() == "Revenir page 2"
    assert reader.page_slider.back_marker == 1
    assert "before" not in store.progress_entry(path)   # montre une seule fois
    reader._resume_back.click()
    assert reader.page == 1 and not reader.resume_banner.isVisible()
    assert store.get_progress(path)[0] == 1 and "device" not in store.progress_entry(path)


def test_live_progress_moves_an_untouched_reader(window, qtbot, mangas, store):
    path = make_cbz(mangas, "Pluto T01", pages=6)
    window.open_manga(path)
    reader = window.reader
    assert reader.page == 0 and not reader.resume_banner.isVisible()
    store.apply_remote_progress(store.key_for(path), 4, 6, False, time.time(), "ipad", before=0)
    window._on_remote_progress(store.key_for(path))
    assert reader.page == 4 and reader.resume_banner.isVisible()


def test_library_shows_the_server_and_where_volumes_are(qtbot, store, mangas):
    from beheread.app import MainWindow
    make_cbz(mangas, "Monster T01")
    store.add_folder(str(mangas))
    store.set_ui_pref("servers_enabled", True)
    store.save_server({"id": "nas", "kind": "beheread", "name": "NAS",
                       "url": "http://127.0.0.1:1", "user": ""}, None)
    win = MainWindow(store)
    qtbot.addWidget(win)
    win.show()
    lib = win.library
    qtbot.waitUntil(lambda: lib.server_pill.isVisible()
                    and "hors ligne" in lib._pill_text.text(), timeout=10000)
    assert lib.server_footer.isVisible()
    assert "Cache hors ligne : 0,0 Go sur 5,0 Go" == lib._cache_label.text()
    qtbot.waitUntil(lambda: lib.list.count() > 0, timeout=10000)
    item = lib.list.item(0)
    assert item.data(ROLE_WHERE) == WHERE_LOCAL
    win.servers.shutdown()


def test_without_beheread_server_nothing_changes(window, qtbot, mangas, store):
    make_cbz(mangas, "Monster T01")
    store.add_folder(str(mangas))
    lib = window.library
    lib.refresh()
    qtbot.waitUntil(lambda: lib.list.count() > 0, timeout=10000)
    assert not lib.server_pill.isVisible() and not lib.server_footer.isVisible()
    assert lib.list.item(0).data(ROLE_WHERE) is None
    assert lib.list.item(0).data(ROLE_PATH)


class _FakeSync:
    def __init__(self, store):
        self.store = store
        self.client = self

    def pair(self):
        return {"code": "R4TN8WZE", "expires": time.time() + 572}

    def me(self):
        return {"admin_name": "Tom", "devices": [
            {"id": "pc", "name": "PC", "kind": "desktop", "current": True, "last_seen": time.time()},
            {"id": "ip", "name": "iPhone de Léa", "kind": "web", "current": False,
             "last_seen": time.time() - 7200}]}


def test_add_device_shows_a_code_and_its_qr_code(qtbot, store):
    from beheread.ui.library.server_dialogs import AddDeviceDialog
    config = ServerConfig(id="nas", kind="beheread", name="NAS", url="https://mangas.exemple.fr")
    dlg = AddDeviceDialog(_FakeSync(store), config)
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: dlg.code.text() == "R4TN 8WZE", timeout=5000)
    assert not dlg.qr.pixmap().isNull()
    assert "encore 9 min" in dlg.validity.text()
    assert "Prévenez Tom" in dlg.lost.text()
    dlg.copy_btn.click()
    assert QApplication.clipboard().text() == "R4TN8WZE"
    dlg.reject()


def test_update_required_dialog(qtbot):
    from beheread.ui.library.server_dialogs import UpdateRequiredDialog
    config = ServerConfig(id="nas", kind="beheread", name="NAS", url="https://mangas.exemple.fr")
    dlg = UpdateRequiredDialog(config, UpdateRequired("x", "1.4.0", "1.3.2"))
    qtbot.addWidget(dlg)
    labels = " ".join(lab.text() for lab in dlg.findChildren(QLabel))
    assert "mangas.exemple.fr" in labels and "1.4.0" in labels and "1.3.2" in labels
