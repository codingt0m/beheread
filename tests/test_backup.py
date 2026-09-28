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


def test_stats_sections_per_device_never_double_count():
    local = {"devices": {"me": {"updated": 10, "days": {"d": {"k": {"pages": 5}}}}}}
    remote = {"devices": {"me": {"updated": 99, "days": {}},          # ma section : ignoree
                          "pc2": {"updated": 20, "days": {"d": {"k": {"pages": 3}}}}}}
    assert backup.merge_stats(local, remote, "me") is True
    assert local["devices"]["me"]["days"]["d"]["k"]["pages"] == 5
    assert local["devices"]["pc2"]["days"]["d"]["k"]["pages"] == 3
    # meme fichier importe une seconde fois : aucun changement, pas de double compte
    assert backup.merge_stats(local, remote, "me") is False


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


def test_invalid_files_are_rejected():
    assert not backup.is_valid({"hello": 1})
    assert not backup.is_valid({"format": "beheread-backup", "version": 99})
    assert not backup.is_valid([1, 2])
