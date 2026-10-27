"""Client « Serveur Beheread » (infra/servers.py), sans serveur : liens
d'invitation, version exigee, identite des tomes par empreinte."""

import pytest

from beheread.infra import servers as remote
from beheread.infra import storage
from beheread.infra.servers import ServerError


def test_parse_invitation():
    assert remote.parse_invitation("https://mangas.exemple.fr/i/K7M2QX9P") == \
        ("https://mangas.exemple.fr", "K7M2QX9P")
    assert remote.parse_invitation("http://192.168.1.93:8000/i/k7m2-qx9p/") == \
        ("http://192.168.1.93:8000", "K7M2QX9P")
    assert remote.parse_invitation(" k7m2 qx9p ") == (None, "K7M2QX9P")


def test_required_version(monkeypatch):
    monkeypatch.setattr("beheread.version.__version__", "1.4.0")
    remote.require_version("1.4.0")
    remote.require_version("1.3.9")
    remote.require_version(None)
    with pytest.raises(ServerError, match="1.10.0"):
        remote.require_version("1.10.0")


def test_server_volume_key_is_its_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "data_dir", lambda: tmp_path)
    store = storage.Store()
    try:
        fp = "c1:" + "ab" * 20
        path = remote.make_path("srv1", remote.FP_BOOK + fp[3:])
        assert store.key_for(path) == fp          # meme cle qu'une copie locale du fichier
        store.set_progress(path, 12, 200, False)
        assert store.progress[fp]["page"] == 12
        komga = remote.make_path("komga", "0A1B")
        assert store.key_for(komga) == komga      # les autres serveurs ne changent pas
    finally:
        store.close()


def test_beheread_kind_is_known():
    config = remote.ServerConfig.from_dict({"id": "s1", "kind": "beheread", "name": "NAS",
                                            "url": "https://mangas.exemple.fr"})
    client = remote.make_client(config, "jeton")
    assert isinstance(client, remote.BeheReadClient) and client.supports_progress
