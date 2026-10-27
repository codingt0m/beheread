"""Tests de la synchronisation d'un profil (profile_sync.py) : regles P1 a P6
du cahier des charges (conflits, hors ligne, double comptage, horloge en
avance), seances deduites des vues de page, reprise."""

import uuid

import pytest

from beheread.core import profile_sync as ps
from beheread.core.profile_sync import EventError, ProfileState

FP = "c1:" + "a" * 40
NOW = 1_800_000_000.0          # heure de reception par le serveur


def ev(kind, device="ipad", ts=NOW - 60, ident=None, **fields):
    return {"id": ident or ps.new_event_id(ts), "type": kind, "device": device, "ts": ts,
            **fields}


def progress(page, device="ipad", ts=NOW - 60, fp=FP, total=200, finished=False, **kw):
    return ev(ps.PROGRESS, device, ts, fp=fp, page=page, total=total, finished=finished, **kw)


def send(state, *events, received=NOW):
    return ps.apply_batch(state, list(events), received)


# ----- identifiants

def test_event_id_is_a_uuid7_ordered_in_time():
    a = ps.new_event_id(1000.0, bytes(10))
    b = ps.new_event_id(1000.001, bytes(10))
    assert uuid.UUID(a).version == 7
    assert uuid.UUID(a).variant == uuid.RFC_4122
    assert a < b


# ----- P1, P2 : la plus recente action l'emporte

def test_progress_is_stored_with_its_action_time():
    state = ProfileState()
    send(state, progress(87, ts=NOW - 30))
    entry = state.progress[FP]
    assert (entry["page"], entry["total"], entry["finished"]) == (87, 200, False)
    assert entry["ts"] == NOW - 30 and entry["device"] == "ipad"


def test_offline_device_does_not_overwrite_a_newer_reading():
    state = ProfileState()
    send(state, progress(120, device="ipad", ts=NOW - 60))
    # le PC, reste hors ligne, envoie une lecture faite AVANT
    result = send(state, progress(40, device="pc", ts=NOW - 3600))
    assert state.progress[FP]["page"] == 120
    assert result["changes"] == []


def test_rereading_from_the_start_elsewhere_is_respected():
    state = ProfileState()
    send(state, progress(180, device="pc", ts=NOW - 3600))
    send(state, progress(5, device="ipad", ts=NOW - 60))   # plus recent, meme si recule
    assert state.progress[FP]["page"] == 5


def test_unknown_fingerprint_is_accepted():
    # P3 : tome present seulement sur un PC
    state = ProfileState()
    result = send(state, progress(10, fp="c1:" + "f" * 40))
    assert result["rejected"] == {}
    assert "c1:" + "f" * 40 in state.progress


# ----- P5, P6 : renvoi d'un paquet, aucun double comptage

def test_resending_a_batch_changes_nothing():
    state = ProfileState()
    batch = [progress(30), ev(ps.JOURNAL, device="pc",
                              rows=[{"day": "2027-02-03", "fp": FP, "pages": 20, "seconds": 600}])]
    first = send(state, *batch)
    again = send(state, *batch)
    assert first["changes"] and again["changes"] == []
    assert sorted(again["accepted"]) == sorted(e["id"] for e in batch)   # le client peut oublier
    assert len(state.journal) == 1


# ----- horloge de l'appareil bornee

def test_future_time_is_brought_back_to_reception():
    state = ProfileState()
    send(state, progress(50, ts=NOW + 86400))     # horloge en avance d'un jour
    assert state.progress[FP]["ts"] == NOW
    # une vraie lecture plus tardive d'un autre appareil l'emporte ensuite
    send(state, progress(60, device="pc", ts=NOW + 10), received=NOW + 20)
    assert state.progress[FP]["page"] == 60


def test_order_of_each_device_is_kept():
    state = ProfileState()
    first = progress(50, ts=NOW + 500)            # ramene a NOW
    second = progress(51, ts=NOW - 10)            # cree apres, mais horloge corrigee entre-temps
    second["id"] = ps.new_event_id(NOW + 501)     # identifiants : ordre de creation
    send(state, first, second)
    assert state.progress[FP]["page"] == 51       # jamais date avant le precedent


# ----- paquets

def test_malformed_events_are_rejected_one_by_one():
    state = ProfileState()
    bad = progress("douze")
    result = send(state, bad, progress(12, fp="c1:" + "b" * 40), {"type": "inconnu"})
    assert set(result["rejected"]) == {bad["id"], "#2"}
    assert len(result["accepted"]) == 1


def test_batch_too_large_is_refused():
    with pytest.raises(EventError):
        ps.apply_batch(ProfileState(), [progress(1)] * (ps.MAX_BATCH + 1), NOW)


@pytest.mark.parametrize("event", [
    {"id": "x", "type": "progress", "device": "d", "ts": 1, "fp": FP, "page": -1, "total": 9,
     "finished": False},
    {"id": "x", "type": "page_views", "device": "d", "ts": 1, "fp": FP, "views": [[[1, 2, 3], 0, 5]]},
    {"id": "x", "type": "journal", "device": "d", "ts": 1, "rows": [{"day": "hier", "fp": FP}]},
    {"id": "", "type": "dismiss", "device": "d", "ts": 1, "target": FP},
])
def test_validate_refuses(event):
    with pytest.raises(EventError):
        ps.validate(event)


# ----- masquages et reglages : meme regle

def test_dismiss_and_reader_override_follow_latest_action():
    state = ProfileState()
    send(state, ev(ps.READER_OVERRIDE, device="pc", ts=NOW - 100, target="series:berserk",
                   setting="double_page", value=True),
         ev(ps.READER_OVERRIDE, device="ipad", ts=NOW - 50, target="series:berserk",
            setting="double_page", value=False),
         ev(ps.DISMISS, ts=NOW - 10, target=FP))
    (override,) = state.overrides.values()
    assert override["value"] is False
    assert state.dismissed[FP]["ts"] == NOW - 10


# ----- seances deduites des vues de page (memes regles que le desktop)

def test_pages_count_only_when_moving_forward():
    rows = ps.sessions_from_views([((0,), 0, 20), ((1, 2), 20, 40), ((3,), 60, 30)])
    # pages 0, 1, 2 lues ; la derniere vue n'est pas suivie d'une avance
    assert rows[0]["pages"] == 3
    assert rows[0]["seconds"] == 90


def test_flicked_pages_and_pauses():
    rows = ps.sessions_from_views([((0,), 0, 0.3),        # feuilletee : rien
                                   ((1,), 1, 600),        # pause : pages lues, temps ignore
                                   ((2,), 601, 10),
                                   ((3,), 611, 5)])
    assert rows[0]["pages"] == 2      # pages 1 et 2
    assert rows[0]["seconds"] == 15


def test_long_gap_starts_a_new_session_dated_in_device_time():
    day_start = 1_800_000_000          # 2027-01-15 08:00 UTC
    views = [((0,), day_start, 20), ((1,), day_start + 20, 20),
             ((5,), day_start + 3 * 3600, 20), ((6,), day_start + 3 * 3600 + 20, 20)]
    rows = ps.sessions_from_views(views, tz_minutes=60)
    assert len(rows) == 2
    assert rows[0]["day"] == "2027-01-15"


def test_page_views_feed_the_journal_once():
    state = ProfileState()
    views = ev(ps.PAGE_VIEWS, fp=FP, views=[[0, NOW - 100, 30], [[1, 2], NOW - 70, 40],
                                             [3, NOW - 30, 10]])
    send(state, views)
    send(state, views)
    (row,) = state.journal
    assert (row["fp"], row["pages"], row["sessions"], row["device"]) == (FP, 3, 1, "ipad")


# ----- reprise (P4)

def test_resume_from_another_device():
    local = {"page": 40, "ts": NOW - 3600, "device": "pc"}
    remote = {"page": 87, "ts": NOW - 300, "device": "ipad"}
    r = ps.resume(local, remote, "pc")
    assert (r.page, r.back_to, r.device) == (87, 40, "ipad")


@pytest.mark.parametrize("local, remote", [
    ({"page": 40, "ts": NOW, "device": "pc"}, {"page": 87, "ts": NOW - 300, "device": "ipad"}),
    ({"page": 40, "ts": NOW - 900, "device": "pc"}, {"page": 87, "ts": NOW, "device": "pc"}),
    ({"page": 87, "ts": NOW - 900, "device": "pc"}, {"page": 87, "ts": NOW, "device": "ipad"}),
    ({"page": 40, "ts": NOW, "device": "pc"}, None),
])
def test_no_resume(local, remote):
    assert ps.resume(local, remote, "pc") is None


def test_resume_without_local_progress():
    r = ps.resume(None, {"page": 12, "ts": NOW, "device": "ipad"}, "pc")
    assert (r.page, r.back_to) == (12, 0)
