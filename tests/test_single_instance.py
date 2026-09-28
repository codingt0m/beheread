"""Tests de l'instance unique (single_instance.py) : format des messages,
verrou exclusif et transmission reelle d'une demande par le canal local."""

import threading
import time
import uuid

import pytest

from beheread.infra import single_instance
from beheread.infra.single_instance import SingleInstance, decode, encode, send_to_primary


def _pump(qapp, seconds):
    from PySide6.QtCore import QCoreApplication, QEvent
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        time.sleep(0.01)


def test_message_roundtrip():
    msg = {"open": "C:\\Mangas\\Berserk — Tome 1.cbz"}
    assert decode(encode(msg).rstrip(b"\n")) == msg


@pytest.mark.parametrize("raw", [b"pas du json", b"[1, 2]", b'{"open": 42}', b"\xff\xfe"])
def test_invalid_messages_are_rejected(raw):
    assert decode(raw) is None


def test_second_instance_does_not_get_the_lock(qapp, tmp_path):
    name = f"beheread-test-{uuid.uuid4().hex[:8]}"
    first = SingleInstance(tmp_path / "instance.lock", name)
    second = SingleInstance(tmp_path / "instance.lock", name)
    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.release()
    # verrou libere : une nouvelle instance peut devenir principale
    third = SingleInstance(tmp_path / "instance.lock", name)
    assert third.acquire() is True
    third.release()


def test_request_is_delivered_to_primary(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(single_instance, "_allow_foreground", lambda: None)
    name = f"beheread-test-{uuid.uuid4().hex[:8]}"
    primary = SingleInstance(tmp_path / "instance.lock", name)
    assert primary.acquire()
    received = []
    primary.messageReceived.connect(received.append)

    # l'envoi est bloquant (waitFor*) : on le fait depuis un autre thread pendant
    # que celui-ci fait tourner la boucle d'evenements du serveur
    result = {}
    sender = threading.Thread(target=lambda: result.setdefault(
        "ok", send_to_primary({"open": "C:\\a.cbz"}, name)))
    sender.start()
    deadline = time.monotonic() + 5
    while not received and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    sender.join(5)
    # nettoyage ordonne : les sockets du serveur (suppression differee) doivent
    # disparaitre avant le serveur lui-meme, sinon Qt peut acceder a un
    # objet deja detruit lors du traitement d'evenements qui suit le test
    _pump(qapp, 0.2)
    primary.release()
    _pump(qapp, 0.1)
    primary.deleteLater()
    _pump(qapp, 0.1)

    assert result.get("ok") is True
    assert received == [{"open": "C:\\a.cbz"}]


def test_send_fails_cleanly_without_primary(qapp, monkeypatch):
    monkeypatch.setattr(single_instance, "_allow_foreground", lambda: None)
    monkeypatch.setattr(single_instance, "CONNECT_ATTEMPTS", 1)
    monkeypatch.setattr(single_instance, "CONNECT_TIMEOUT_MS", 50)
    assert send_to_primary({"activate": True}, f"beheread-absent-{uuid.uuid4().hex}") is False
