"""Tests de la connexion AniList : configuration de l'application, recepteur
local du jeton (anilist_auth.py) et regle d'envoi en fin de seance."""

import json
import socket
import time
import urllib.error
import urllib.request

import pytest

from beheread import config
from beheread.core import anilist_track as track
from beheread.infra.anilist_auth import LocalAuthReceiver


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(port, body, origin):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/anilist/done", data=json.dumps(body).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json", "Origin": origin})
    return urllib.request.urlopen(req, timeout=5).status


def _wait(qapp, cond, t=5):
    end = time.monotonic() + t
    while time.monotonic() < end and not cond():
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


@pytest.fixture
def receiver(qapp):
    port = _free_port()
    r = LocalAuthReceiver(port, "/anilist")
    r.start()
    yield r
    r.stop()


def test_client_id_from_config_or_environment(monkeypatch):
    monkeypatch.setattr(config, "ANILIST_CLIENT_ID", "")
    monkeypatch.delenv("BEHEREAD_ANILIST_CLIENT_ID", raising=False)
    assert config.anilist_client_id() == ""
    monkeypatch.setenv("BEHEREAD_ANILIST_CLIENT_ID", " 12345 ")
    assert config.anilist_client_id() == "12345"
    assert config.anilist_redirect_uri().startswith("http://127.0.0.1:")


def test_callback_page_is_served(receiver):
    html = urllib.request.urlopen(f"{receiver.origin}/anilist", timeout=5).read().decode("utf-8")
    assert "access_token" in html and "/anilist/done" in html


def test_token_accepted_from_own_page(qapp, receiver):
    got = []
    receiver.tokenReceived.connect(got.append)
    assert _post(receiver.port, {"token": "jwt-abc"}, receiver.origin) == 204
    assert _wait(qapp, lambda: got) and got == ["jwt-abc"]


def test_token_refused_from_another_site(qapp, receiver):
    got = []
    receiver.tokenReceived.connect(got.append)
    with pytest.raises(urllib.error.HTTPError) as err:
        _post(receiver.port, {"token": "injecte"}, "https://site-malveillant.example")
    assert err.value.code == 403
    qapp.processEvents()
    assert got == []


def test_user_refusal_reports_failure(qapp, receiver):
    errors = []
    receiver.failed.connect(errors.append)
    _post(receiver.port, {"error": "access_denied"}, receiver.origin)
    assert _wait(qapp, lambda: errors) and errors == ["access_denied"]


def test_port_already_taken_raises(qapp):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = LocalAuthReceiver(s.getsockname()[1], "/anilist")
        with pytest.raises(OSError):
            busy.start()


def test_session_end_only_pushes_new_progress():
    assert track.is_new_progress({"volumes": 3}, None)
    assert track.is_new_progress({"volumes": 4}, {"volumes": 3})
    assert not track.is_new_progress({"volumes": 3}, {"volumes": 3})
    assert not track.is_new_progress(None, None)
    assert track.is_new_progress({"volumes": 3, "chapters": 12}, {"volumes": 3, "chapters": 10})
