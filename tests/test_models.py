"""Tests des modeles de donnees (beheread.core.models)."""

import dataclasses

import pytest

from beheread.core.models import LibraryEntry


def test_roundtrip_through_persisted_dict():
    e = LibraryEntry(path="C:/m/Berserk T1.cbz", title="Berserk T1", series="Berserk",
                     volume=1, kind="volume", added=12.5, manual=True)
    assert LibraryEntry.from_dict(e.to_dict()) == e


def test_entries_are_immutable():
    e = LibraryEntry(path="a", title="a", series="a")
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.title = "b"


def test_old_index_without_new_fields_is_accepted():
    """Instantane ecrit par une version plus ancienne (sans kind/manual)."""
    e = LibraryEntry.from_dict({"path": "a.cbz", "title": "A", "series": "A", "volume": 3,
                                "added": 5, "detached": False})
    assert e.volume == 3 and e.kind is None and e.manual is False


@pytest.mark.parametrize("bad", [None, [], "x", {}, {"path": "a.cbz"}, {"title": "A"},
                                 {"path": 3, "title": "A"}])
def test_damaged_index_entries_are_ignored(bad):
    assert LibraryEntry.from_dict(bad) is None


def test_bad_field_values_are_sanitized():
    e = LibraryEntry.from_dict({"path": "a.cbz", "title": "A", "volume": "12",
                                "added": "hier", "kind": 4})
    assert e.volume is None and e.added == 0.0 and e.kind is None and e.series == "A"
