"""Tests du service de suivi AniList (file d'attente, resultats d'envoi).
Aucun appel reseau : les resultats du thread d'envoi sont simules."""

from beheread.services.anilist_tracker import AniListTracker
from tests.test_storage import store  # noqa: F401  (fixture)


def _updated(desired):
    return {"series_key": "berserk", "status": "updated", "desired": desired,
            "title": "Berserk", "summary": "tome(s) lu(s)"}


def test_sent_progress_leaves_the_queue(qapp, store):  # noqa: F811
    tracker = AniListTracker(store, lambda _p: None)
    pending = store.anilist_series("pending")
    pending["berserk"] = {"name": "Berserk", "desired": {"volumes": 5}}
    tracker._on_done([_updated({"volumes": 5})])
    assert "berserk" not in pending
    assert store.anilist_series("last")["berserk"]["pushed"] == {"volumes": 5}
    assert not tracker._debounce.isActive()


def test_progress_queued_during_send_is_kept(qapp, store):  # noqa: F811
    """Un tome termine pendant l'envoi remplace l'attente de la serie : la
    reponse de l'envoi precedent ne doit pas l'effacer."""
    tracker = AniListTracker(store, lambda _p: None)
    pending = store.anilist_series("pending")
    pending["berserk"] = {"name": "Berserk", "desired": {"volumes": 6}}
    tracker._on_done([_updated({"volumes": 5})])
    assert pending["berserk"]["desired"] == {"volumes": 6}
    assert store.anilist_series("last")["berserk"]["pushed"] == {"volumes": 5}
    assert tracker._debounce.isActive()   # renvoi programme


def _run_worker(monkeypatch, search, media, desired):
    """Execute le thread d'envoi sur place, AniList simule ; renvoie
    (resultat, ecritures envoyees)."""
    from beheread.infra import anilist
    from beheread.services.anilist_tracker import _TrackWorker
    saved = []
    monkeypatch.setattr(anilist, "search_series", lambda name: search)
    monkeypatch.setattr(anilist, "media_entry", lambda token, media_id: media)
    monkeypatch.setattr(anilist, "save_entry",
                        lambda token, media_id, changes, entry: saved.append((media_id, changes)))
    worker = _TrackWorker("jeton", [{"series_key": "errance", "name": "Errance",
                                     "desired": desired, "media_id": None}])
    results = []
    worker.signals.done.connect(results.extend)
    worker.run()
    return results[0], saved


ONESHOT = {"volumes": 1, "oneshot": True}


def test_oneshot_is_published_as_completed(qapp, monkeypatch):
    res, saved = _run_worker(
        monkeypatch, {"anilist_id": 98674, "title": "Downfall", "match_score": 1.0},
        {"id": 98674, "title": "Downfall", "volumes": 1, "entry": None}, ONESHOT)
    assert res["status"] == "updated"
    assert saved == [(98674, {"progressVolumes": 1, "status": "COMPLETED"})]


def test_oneshot_of_multi_volume_work_is_skipped(qapp, monkeypatch):
    res, saved = _run_worker(
        monkeypatch, {"anilist_id": 1, "title": "Long", "match_score": 1.0},
        {"id": 1, "title": "Long", "volumes": 12, "entry": None}, ONESHOT)
    assert res["status"] == "skipped" and saved == []


def test_oneshot_with_loose_title_match_is_not_associated(qapp, monkeypatch):
    res, saved = _run_worker(
        monkeypatch, {"anilist_id": 45021, "title": "iLLUMiNATiON", "match_score": 0.649},
        {"id": 45021, "volumes": 1, "entry": None}, ONESHOT)
    assert res["status"] == "unmatched" and saved == []


def test_skipped_oneshot_leaves_the_queue_with_a_reason(qapp, store):  # noqa: F811
    tracker = AniListTracker(store, lambda _p: None)
    pending = store.anilist_series("pending")
    pending["errance"] = {"name": "Errance", "desired": ONESHOT}
    tracker._on_done([{"series_key": "errance", "status": "skipped", "desired": ONESHOT,
                       "title": "Long", "summary": "œuvre en plusieurs tomes : rien publié"}])
    assert "errance" not in pending
    assert "plusieurs tomes" in tracker.series_state("errance")[0]


def test_unexpected_error_still_reports_the_batch(qapp, monkeypatch):
    """Une reponse inattendue d'AniList ne doit pas laisser le suivi bloque :
    le signal de fin part toujours, le travail est compte en erreur."""
    from beheread.infra import anilist
    from beheread.services.anilist_tracker import _TrackWorker

    def broken(token, media_id):
        raise AttributeError("'NoneType' object has no attribute 'get'")

    monkeypatch.setattr(anilist, "media_entry", broken)
    worker = _TrackWorker("jeton", [{"series_key": "errance", "name": "Errance",
                                     "desired": {"volumes": 2}, "media_id": 5}])
    results = []
    worker.signals.done.connect(results.append)
    worker.run()
    assert len(results) == 1
    assert results[0][0]["status"] == "error"


def test_reading_events_reach_every_tracker(qapp, store):  # noqa: F811
    """L'application ne parle qu'a l'interface commune : chaque service de
    suivi recoit les fins de tome et de seance."""
    from beheread.services.tracking import Tracker, TrackerSet

    class Recorder(Tracker):
        def __init__(self):
            super().__init__()
            self.events = []

        def on_volumes_finished(self, paths):
            self.events.append(("fin", tuple(paths)))

        def on_session_end(self, path):
            self.events.append(("seance", path))

        def flush_pending(self):
            self.events.append(("envoi",))

    anilist = AniListTracker(store, lambda _p: None)
    assert isinstance(anilist, Tracker) and anilist.NAME == "AniList"
    a, b = Recorder(), Recorder()
    trackers = TrackerSet([a, b])
    trackers.on_volumes_finished(["t1"])
    trackers.on_session_end("t1")
    trackers.flush_pending()
    assert a.events == b.events == [("fin", ("t1",)), ("seance", "t1"), ("envoi",)]
