"""Tests de la fusion export/import de sauvegarde (backup.py)."""

import json

from beheread.core import backup


def test_newer_progress_wins():
    local = {"c1:a": {"page": 3, "ts": 100}, "c1:b": {"page": 9, "ts": 500}}
    remote = {"c1:a": {"page": 7, "ts": 200}, "c1:b": {"page": 1, "ts": 400},
              "c1:c": {"page": 2, "ts": 50}}
    changed = backup.merge_progress(local, remote)
    assert sorted(changed) == ["c1:a", "c1:c"]
    assert local["c1:a"]["page"] == 7 and local["c1:b"]["page"] == 9


def test_path_keyed_entries_are_not_imported():
    local = {}
    backup.merge_progress(local, {"C:\\x.cbz": {"page": 1, "ts": 9}})
    assert local == {}


def test_journal_sections_per_device_never_double_count():
    pc2 = {"updated": 20, "days": {"d": {"k": {"pages": 3}}}}
    remote = {"devices": {"me": {"updated": 99, "days": {}},          # ma section : ignoree
                          "pc2": pc2, "abime": "pas une section"}}
    assert backup.journal_sections_to_import({"me": 10}, remote, "me") == {"pc2": pc2}
    # meme fichier importe une seconde fois : rien a reprendre, pas de double compte
    assert backup.journal_sections_to_import({"me": 10, "pc2": 20}, remote, "me") == {}
    # section plus recente que celle deja connue : reprise
    assert backup.journal_sections_to_import({"pc2": 5}, remote, "me") == {"pc2": pc2}
    assert backup.journal_sections_to_import({}, {"devices": "abime"}, "me") == {}


def test_dismissed_keeps_latest():
    local = {"c1:a": 10}
    assert backup.merge_dismissed(local, {"c1:a": 20, "c1:b": 5}) is True
    assert local == {"c1:a": 20, "c1:b": 5}


def test_backup_roundtrip_adds_missing_settings_and_manual_meta():
    data = backup.build_backup(
        {"series_names": {"berserk": "Berserk (prestige)"}, "folders": ["C:\\x"]},
        {"c1:a": {"page": 4, "ts": 10}}, {"devices": {"me": {"updated": 1}}},
        {"volume": {"c1:a": {"authors": ["Miura"], "source": "manual"},
                    "c1:b": {"authors": ["X"], "source": "googlebooks"}}},
        {}, "me", "PC")
    assert backup.is_valid(data)
    assert "folders" not in data["settings"]             # chemins propres a un PC
    assert list(data["meta_manual"]["volume"]) == ["c1:a"]

    settings = {"series_names": {"berserk": "Local"}}
    meta = {"volume": {}}
    added = backup.merge_extras(settings, meta, json.loads(json.dumps(data)))
    assert settings["series_names"]["berserk"] == "Local"   # jamais ecrase
    assert meta["volume"]["c1:a"]["authors"] == ["Miura"]
    assert added == 1


def test_virtual_volume_progress_and_definition_are_backed_up():
    vpath = "beheread-virtual:abc/Berserk - Tome 44.cbz"
    definition = {"abc": {"series": "berserk", "name": "Berserk", "number": 44,
                          "chapters": ["c1:x", "c1:y"]}}
    data = backup.build_backup({"virtual_volumes": definition},
                               {vpath: {"page": 12, "ts": 10}, "/old/path.cbz": {"page": 1}},
                               {}, {}, {}, "me", "PC")
    assert list(data["progress"]) == [vpath]               # pas un ancien chemin de fichier
    assert data["settings"]["virtual_volumes"] == definition
    local = {}
    assert backup.merge_progress(local, data["progress"]) == [vpath]
    settings = {}
    backup.merge_extras(settings, {}, json.loads(json.dumps(data)))
    assert settings["virtual_volumes"] == definition


def test_invalid_files_are_rejected():
    assert not backup.is_valid({"hello": 1})
    assert not backup.is_valid({"format": "beheread-backup", "version": 99})
    assert not backup.is_valid([1, 2])


# ---- sauvegarde forgee ou abimee : rien d'inattendu n'est enregistre

def test_malformed_progress_entries_are_ignored():
    """Une page en texte casserait la bibliotheque a chaque affichage une fois
    enregistree (comparaison avec un entier dans is_started)."""
    local = {}
    remote = {"c1:texte": {"page": "12", "total": 40, "ts": 5},
              "c1:ts": {"page": 1, "total": 40, "ts": [1, 2]},
              "c1:neg": {"page": -3, "total": 40, "ts": 5},
              "c1:bool": {"page": True, "total": 40, "ts": 5},
              "c1:ok": {"page": 4.0, "total": 40, "finished": 1, "ts": 7, "x": "<img>"}}
    assert backup.merge_progress(local, remote) == ["c1:ok"]
    assert local == {"c1:ok": {"page": 4, "total": 40, "finished": True, "ts": 7.0}}


def test_malformed_local_progress_does_not_block_the_import():
    local = {"c1:a": {"page": 1, "ts": "abime"}}
    assert backup.merge_progress(local, {"c1:a": {"page": 2, "total": 9, "ts": 3}}) == ["c1:a"]


def test_extras_of_unexpected_type_are_ignored():
    settings, meta = {}, {}
    data = {"settings": {"pages": {"c1:a": "12", "c1:b": True, "c1:c": 30},
                         "volume_direction": {"c1:a": "oui", "c1:b": False},
                         "added": {"c1:a": None, "c1:b": 1700000000.5},
                         "folders": {"x": "C:\\"}},
            "meta_manual": {"volume": {"c1:a": "texte", "c1:b": {"source": "googlebooks"},
                                       "c1:c": {"source": "manual", "authors": ["Miura"]}},
                            "autre": {"c1:d": {"source": "manual"}}}}
    assert backup.merge_extras(settings, meta, data) == 4
    assert settings == {"pages": {"c1:c": 30}, "volume_direction": {"c1:b": False},
                        "added": {"c1:b": 1700000000.5}}
    assert meta == {"volume": {"c1:c": {"source": "manual", "authors": ["Miura"]}}}


def test_dismissed_entries_must_be_timestamps():
    local = {"c1:a": 10}
    assert backup.merge_dismissed(local, {"c1:a": "20", "c1:b": float("nan"),
                                          "c1:c": 30, "c1:d": True}) is True
    assert local == {"c1:a": 10, "c1:c": 30}
    assert backup.merge_dismissed(local, ["pas un dict"]) is False


def test_oversized_file_is_refused_before_being_read(tmp_path, monkeypatch):
    import pytest

    from beheread.infra import storage
    monkeypatch.setattr(storage, "data_dir", lambda: tmp_path / "data")
    (tmp_path / "data").mkdir()
    store = storage.Store()
    big = tmp_path / "enorme.json"
    big.write_bytes(b" " * 2048)
    monkeypatch.setattr(storage, "MAX_BACKUP_BYTES", 1024)
    with pytest.raises(ValueError, match="trop volumineux"):
        store.import_backup(big)
    store.close()
