"""Tests du client AniList (reseau simule) et des regles du suivi de lecture."""

import io
import json
import urllib.error

import pytest

from beheread.infra import anilist
from beheread.core import anilist_track as track


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(payload, captured=None, status=None):
    def urlopen(req, timeout=None):
        if captured is not None:
            captured.append(req)
        if status is not None:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(b"{}"))
        return _Resp(json.dumps(payload).encode("utf-8"))
    return urlopen


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(anilist, "_throttle", lambda: None)


# ---------------------------------------------------------------- client

def test_search_series_returns_id_and_match_score(monkeypatch):
    media = {"id": 30002, "title": {"romaji": "Berserk", "english": "Berserk", "native": "ベルセルク"},
             "synonyms": [], "staff": {"nodes": [{"name": {"full": "Kentarou Miura"}}]},
             "startDate": {"year": 1989}, "countryOfOrigin": "JP", "volumes": None, "chapters": None}
    monkeypatch.setattr(anilist.urllib.request, "urlopen", _fake_urlopen({"data": {"Media": media}}))
    r = anilist.search_series("Berserk")
    assert r["anilist_id"] == 30002 and r["authors"] == ["Kentarou Miura"]
    assert r["match_score"] >= 0.9


def test_search_series_low_score_for_unrelated_title(monkeypatch):
    media = {"id": 1, "title": {"romaji": "Tokyo Ghoul"}, "synonyms": [],
             "staff": {"nodes": []}, "startDate": {}, "volumes": 14}
    monkeypatch.setattr(anilist.urllib.request, "urlopen", _fake_urlopen({"data": {"Media": media}}))
    r = anilist.search_series("Les Gouttes de Dieu")
    assert r["match_score"] < track.AUTO_MATCH_MIN_SCORE
    assert track.auto_match(r) is None


def test_search_not_found_is_none(monkeypatch):
    monkeypatch.setattr(anilist.urllib.request, "urlopen", _fake_urlopen({}, status=404))
    assert anilist.search_series("zzz") is None


def test_token_is_sent_and_rejection_raises_auth_error(monkeypatch):
    captured = []
    monkeypatch.setattr(anilist.urllib.request, "urlopen",
                        _fake_urlopen({"data": {"Viewer": {"id": 7, "name": "tom"}}}, captured))
    assert anilist.viewer("secret") == {"id": 7, "name": "tom"}
    assert captured[0].get_header("Authorization") == "Bearer secret"
    monkeypatch.setattr(anilist.urllib.request, "urlopen", _fake_urlopen({}, status=401))
    with pytest.raises(anilist.AniListAuthError):
        anilist.viewer("expire")


def test_save_entry_sends_only_known_fields(monkeypatch):
    captured = []
    monkeypatch.setattr(anilist.urllib.request, "urlopen", _fake_urlopen(
        {"data": {"SaveMediaListEntry": {"status": "CURRENT", "progressVolumes": 5}}}, captured))
    anilist.save_entry("t", 30002, {"progressVolumes": 5, "status": "CURRENT"}, None)
    sent = json.loads(captured[0].data)["variables"]
    assert sent == {"mediaId": 30002, "progressVolumes": 5, "status": "CURRENT"}


def test_parse_media_ref():
    assert anilist.parse_media_ref("https://anilist.co/manga/30002/Berserk/") == 30002
    assert anilist.parse_media_ref(" 30002 ") == 30002
    assert anilist.parse_media_ref("https://anilist.co/anime/1") is None
    assert anilist.parse_media_ref("berserk") is None


def test_authorize_url():
    url = anilist.authorize_url(" 12345 ")
    assert url.startswith(anilist.AUTHORIZE_URL) and "client_id=12345" in url
    assert "response_type=token" in url


# ---------------------------------------------------------------- regles du suivi

def test_desired_progress_highest_finished():
    vols = [(1, "volume", True), (2, "volume", True), (5, "volume", True),
            (6, "volume", False), (None, None, True), (12.5, "chapter", True)]
    assert track.desired_progress(vols) == {"volumes": 5, "chapters": 12}
    assert track.desired_progress([(1, "volume", False)]) is None


def test_plan_never_decreases():
    media = {"volumes": None, "entry": {"status": "CURRENT", "progressVolumes": 8}}
    assert track.plan_update({"volumes": 5}, media) is None
    assert track.plan_update({"volumes": 9}, media) == {"progressVolumes": 9}


def test_plan_adds_to_list_as_current():
    media = {"volumes": 41, "entry": None}
    assert track.plan_update({"volumes": 3}, media) == {"progressVolumes": 3, "status": "CURRENT"}


def test_plan_completes_when_last_volume_read():
    media = {"volumes": 12, "entry": {"status": "CURRENT", "progressVolumes": 11}}
    assert track.plan_update({"volumes": 12}, media) == {"progressVolumes": 12,
                                                         "status": "COMPLETED"}


@pytest.mark.parametrize("status", ["COMPLETED", "DROPPED", "PAUSED"])
def test_plan_respects_user_status(status):
    media = {"volumes": None, "entry": {"status": status, "progressVolumes": 1}}
    assert track.plan_update({"volumes": 5}, media) is None


def test_describe():
    assert track.describe({"progressVolumes": 12, "status": "COMPLETED"}) == \
        "12 tome(s) lu(s), série terminée"


# ---------------------------------------------------------------- uniquement ajouter

@pytest.mark.parametrize("changes, entry", [
    ({"progressVolumes": 3}, {"status": "CURRENT", "progressVolumes": 5}),     # recul
    ({"progress": 10}, {"status": "CURRENT", "progress": 12}),                 # recul chapitres
    ({"progressVolumes": 9}, {"status": "COMPLETED", "progressVolumes": 8}),   # entree terminee
    ({"progressVolumes": 9}, {"status": "REPEATING", "progressVolumes": 2}),   # relecture
    ({"progressVolumes": 9}, {"status": "DROPPED"}),
    ({"progressVolumes": 9}, {"status": "PAUSED"}),
    ({"status": "PLANNING"}, {"status": "CURRENT"}),                           # retour en arriere
    ({"status": "DROPPED"}, {"status": "CURRENT"}),
    ({"score": 0}, {"status": "CURRENT"}),                                     # autre champ
    ({"notes": ""}, None),
    ({}, None),
])
def test_non_additive_updates_are_refused(changes, entry):
    assert not track.is_additive(changes, entry)


@pytest.mark.parametrize("changes, entry", [
    ({"progressVolumes": 1, "status": "CURRENT"}, None),                       # ajout a la liste
    ({"progressVolumes": 4, "status": "CURRENT"}, {"status": "PLANNING"}),
    ({"progressVolumes": 6}, {"status": "CURRENT", "progressVolumes": 5}),
    ({"progressVolumes": 41, "status": "COMPLETED"}, {"status": "CURRENT", "progressVolumes": 40}),
])
def test_additive_updates_are_allowed(changes, entry):
    assert track.is_additive(changes, entry)


def test_every_plan_is_additive():
    """Tout ce que plan_update propose passe le garde-fou."""
    for status in (None, "PLANNING", "CURRENT", "COMPLETED", "PAUSED", "DROPPED", "REPEATING"):
        for have in (0, 3, 12):
            for want in (1, 3, 5, 12, 41):
                media = {"volumes": 41, "entry": {"status": status, "progressVolumes": have} if status else None}
                changes = track.plan_update({"volumes": want}, media)
                if changes:
                    assert track.is_additive(changes, media["entry"]), (status, have, want, changes)


def test_save_entry_refuses_decrease_without_network(monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("aucune requete ne doit partir")
    monkeypatch.setattr(anilist.urllib.request, "urlopen", no_network)
    with pytest.raises(anilist.AniListRefused):
        anilist.save_entry("t", 1, {"progressVolumes": 2}, {"status": "CURRENT", "progressVolumes": 7})


def test_delete_queries_can_never_be_sent(monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("aucune requete ne doit partir")
    monkeypatch.setattr(anilist.urllib.request, "urlopen", no_network)
    with pytest.raises(anilist.AniListRefused):
        anilist._post("mutation ($id: Int) { DeleteMediaListEntry(id: $id) { deleted } }",
                      {"id": 1}, "t")
