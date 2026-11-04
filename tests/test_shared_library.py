"""Donnees de bibliotheque partagees par un serveur Beheread
(infra/shared_library.py) : ce qui part de Beheread Admin, et ce que chaque
client recopie dans sa propre bibliotheque."""

from beheread.infra import shared_library
from beheread.infra.storage import LibraryStore

FP = "c1:" + "a" * 40
FP2 = "c1:" + "b" * 40


def _store(tmp_path, name="lib"):
    return LibraryStore(tmp_path / name, "bibliotheque.db")


def test_export_keeps_only_shareable_data(tmp_path):
    lib = _store(tmp_path)
    lib.set_series_override(FP, "Berserk")
    lib.set_series_name("berserk", "Berserk Deluxe")
    lib.set_volume_meta(FP, {"source": "manual", "authors": ["Miura"]})
    lib.set_volume_meta(FP2, {"source": "server", "authors": ["Miura"]})   # donne par le serveur
    lib.settings.setdefault("covers", {})[FP] = {"page": 2}
    lib.settings["covers"][FP2] = {"image": "x.jpg"}                       # fichier : pas ici
    out = shared_library.export(lib)
    assert out["overrides"] == {FP: "Berserk"}
    assert out["series_names"] == {"berserk": "Berserk Deluxe"}
    assert out["volume_meta"] == {FP: {"source": "manual", "authors": ["Miura"]}}
    assert out["covers"] == {FP: {"page": 2}}
    lib.close()


def test_apply_copies_then_removes_only_what_the_server_gave(tmp_path):
    admin, client = _store(tmp_path, "admin"), _store(tmp_path, "client")
    admin.set_series_override(FP, "Berserk")
    admin.set_series_name("berserk", "Berserk Deluxe")
    client.set_series_name("monster", "Monster (perso)")    # correction locale du client
    assert shared_library.apply(client, "srv", shared_library.export(admin))
    assert client.series_override(FP) == "Berserk"
    assert client.series_name("berserk") == "Berserk Deluxe"
    assert not shared_library.apply(client, "srv", shared_library.export(admin))   # rien de neuf
    # l'administrateur annule ses corrections : le client suit, sa correction reste
    admin.clear_series_override(FP)
    admin.set_series_name("berserk", None)
    assert shared_library.apply(client, "srv", shared_library.export(admin))
    assert client.series_override(FP) is None
    assert client.series_name("berserk") is None
    assert client.series_name("monster") == "Monster (perso)"
    admin.close()
    client.close()


def test_apply_skips_pending_local_edits(tmp_path):
    client = _store(tmp_path)
    client.set_series_name("berserk", "Nouveau nom, pas encore envoye")
    shared = {"series_names": {"berserk": "Ancien nom"}}
    shared_library.apply(client, "srv", shared, skip=lambda s, k: (s, k) == ("series_names", "berserk"))
    assert client.series_name("berserk") == "Nouveau nom, pas encore envoye"
    client.close()


def test_apply_survives_restart(tmp_path):
    client = _store(tmp_path)
    shared_library.apply(client, "srv", {"overrides": {FP: "Pluto"},
                                         "virtual_volumes": {"v1": {"series": "pluto", "number": 2}}})
    client.close()
    again = _store(tmp_path)
    assert again.series_override(FP) == "Pluto"
    assert again.virtual_volumes() == {"v1": {"series": "pluto", "number": 2}}
    shared_library.apply(again, "srv", {})
    assert again.series_override(FP) is None and again.virtual_volumes() == {}
    again.close()


def test_garbage_is_ignored(tmp_path):
    client = _store(tmp_path)
    assert not shared_library.apply(client, "srv", "pas un dict")
    shared_library.apply(client, "srv", {"overrides": {"": "x", FP: "ok"}, "inconnu": {"a": 1},
                                         "covers": {FP: {"image": "../../x.jpg"}}})
    assert client.series_override(FP) == "ok"
    assert client.custom_cover(FP) is None
    client.close()
