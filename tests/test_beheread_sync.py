"""Synchronisation d'un profil avec un serveur Beheread
(services/beheread_sync.py), contre un faux client en memoire : file
d'evenements, changements des autres appareils, reprise, journal, version
exigee. L'essai contre le vrai serveur est dans le depot prive du serveur."""

import queue
import time

import pytest

from beheread.infra import storage
from beheread.infra.servers import ServerConfig, UpdateRequired
from beheread.services import beheread_sync
from beheread.services.beheread_sync import BeheReadSync

FP = "c1:" + "ab" * 20
OTHER = "c1:" + "cd" * 20


class FakeClient:
    """Le minimum du client BeheReadClient dont la synchronisation se sert."""

    def __init__(self):
        self.config = ServerConfig(id="nas", kind="beheread", name="NAS",
                                   url="http://127.0.0.1:1")
        self.sent = []
        self.feed = []          # changements du profil, dans l'ordre
        self.minimum = None
        self.sections = {}
        self.snapshot = {"cursor": 0, "progress": {}, "dismissed": {}}
        self.pushes = queue.Queue()

    def version(self):
        if self.minimum:
            raise UpdateRequired("trop ancien", self.minimum, "1.3.0")
        return {"desktop_min": None}

    def me(self):
        return {"device": "pc", "profile": {"name": "Léa", "color": "#335577"},
                "devices": [{"id": "pc", "name": "PC"}, {"id": "ipad", "name": "iPad de Léa"}]}

    def send_events(self, events):
        self.sent += events
        return {"accepted": [e["id"] for e in events], "rejected": {}}

    def changes(self, since, library):
        return {"cursor": {"profile": len(self.feed), "library": 1},
                "changes": self.feed[since:]}

    def profile(self):
        return self.snapshot

    def journal(self, device=""):
        return self.sections

    def listen(self, on_event, stop):
        on_event("hello", "1")
        while not stop.is_set():
            try:
                on_event(self.pushes.get(timeout=0.05), "1")
            except queue.Empty:
                pass

    def change(self, repo, key, value):
        self.feed.append({"feed": "profile", "repo": repo, "key": key, "value": value})
        self.pushes.put("change")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "data_dir", lambda: tmp_path)
    s = storage.Store()
    yield s
    s.close()


@pytest.fixture
def sync(qtbot, store, monkeypatch):
    monkeypatch.setattr(beheread_sync, "FLUSH_MS", 50)
    client = FakeClient()
    created = []

    def make(start=True):
        s = BeheReadSync(store, client)
        created.append(s)
        if start:
            s.start()
            qtbot.waitUntil(lambda: s.state == beheread_sync.ONLINE and s.live, timeout=3000)
        return s
    make.client = client
    yield make
    for s in created:
        s.stop()


def test_page_turns_are_grouped_and_sent(qtbot, store, sync):
    s = sync()
    client = sync.client
    for page in range(1, 6):
        store.set_progress(FP, page, 20, False)
    store.set_progress("beheread-virtual:serie", 3, 9, False)   # sans empreinte : ignore
    qtbot.waitUntil(lambda: bool(client.sent) and not store.sync_state("nas")["queue"],
                    timeout=3000)
    progress = [e for e in client.sent if e["type"] == "progress"]
    assert [e["page"] for e in progress] == [5]   # une seule par tome : la plus recente
    assert progress[0]["fp"] == FP and progress[0]["total"] == 20
    assert s.device_id == "pc"


def test_journal_dismiss_and_reset_become_events(qtbot, store, sync):
    sync()
    client = sync.client
    store.set_progress(FP, 4, 20, False)
    store.record_reading(FP, 3, 90.0, False, "Berserk T01", "Berserk")
    store.dismiss_continue(FP)
    store.remove_progress(FP)
    qtbot.waitUntil(lambda: len(client.sent) >= 3, timeout=3000)
    kinds = {e["type"]: e for e in client.sent}
    assert kinds["journal"]["rows"][0] == {
        "day": time.strftime("%Y-%m-%d"), "pages": 3, "seconds": 90.0, "finished": False,
        "title": "Berserk T01", "series": "Berserk", "fp": FP}
    assert kinds["dismiss"]["target"] == FP
    assert kinds["progress"]["page"] == 0 and kinds["progress"]["total"] == 0   # remis a zero


def test_reading_on_another_device_is_resumed_here(qtbot, store, sync):
    sync()
    client = sync.client
    store.set_progress(FP, 39, 212, False)   # lu ici jusqu'a la page 40
    later = time.time() + 5
    client.change("progress", FP, {"page": 86, "total": 212, "finished": False,
                                   "ts": later, "device": "ipad"})
    qtbot.waitUntil(lambda: store.get_progress(FP)[0] == 86, timeout=3000)
    entry = store.progress_entry(FP)
    assert entry["device"] == "ipad" and entry["before"] == 39
    # une seconde lecture ailleurs garde la page d'ici comme point de retour
    client.change("progress", FP, {"page": 90, "total": 212, "finished": False,
                                   "ts": later + 1, "device": "ipad"})
    qtbot.waitUntil(lambda: store.get_progress(FP)[0] == 90, timeout=3000)
    assert store.progress_entry(FP)["before"] == 39
    store.forget_resume(FP)
    assert "before" not in store.progress_entry(FP)
    # lu ici ensuite : la progression redevient celle de ce PC
    store.set_progress(FP, 91, 212, False)
    assert "device" not in store.progress_entry(FP)


def test_own_and_older_changes_are_ignored(qtbot, store, sync):
    sync()
    client = sync.client
    store.set_progress(FP, 10, 20, False)
    ts = store.progress_entry(FP)["ts"]
    client.change("progress", FP, {"page": 2, "total": 20, "finished": False,
                                   "ts": ts - 60, "device": "ipad"})   # plus ancienne
    client.change("progress", FP, {"page": 3, "total": 20, "finished": False,
                                   "ts": ts + 60, "device": "pc"})     # la notre
    client.change("progress", OTHER, {"page": 0, "total": 0, "finished": False,
                                      "ts": time.time() + 60, "device": "ipad"})
    store.set_progress(OTHER, 5, 20, False)
    qtbot.waitUntil(lambda: store.sync_state("nas").get("cursor") == 3, timeout=3000)
    assert store.get_progress(FP)[0] == 10
    assert store.get_progress(OTHER) is None   # remis a zero sur l'iPad, plus tard


def test_other_devices_journal_joins_the_statistics(qtbot, store, sync):
    client = sync.client
    today = time.strftime("%Y-%m-%d")
    section = {"name": "iPad de Léa", "updated": time.time(), "rules": 2,
               "days": {today: {FP: {"pages": 12, "seconds": 300.0, "sessions": 1,
                                     "finished": 0, "title": "Berserk T01",
                                     "series": "Berserk"}}}}
    client.sections = {"ipad": section, store.device_id(): section}   # la sienne : ignoree
    sync()
    qtbot.waitUntil(lambda: "ipad" in store.reading_log.devices(), timeout=3000)
    assert store.device_id() not in store.reading_log.devices()


def test_outdated_application_keeps_its_queue(qtbot, store, sync):
    sync.client.minimum = "9.0.0"
    store.set_progress(FP, 4, 20, False)   # avant la connexion : rattrape au demarrage
    s = sync(start=False)
    s.start()
    qtbot.waitUntil(lambda: s.state == beheread_sync.UPDATE, timeout=3000)
    assert s.update.minimum == "9.0.0"
    assert [e["page"] for e in store.sync_state("nas")["queue"]] == [4]
    assert sync.client.sent == []
