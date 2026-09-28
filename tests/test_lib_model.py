"""Tests de la logique pure de la bibliotheque (library_model.py)."""

import dataclasses

from beheread.core.models import VolumeInfo
from beheread.core.library_model import (ALL, FINISHED, READING, UNREAD, aggregate_series_info,
                       continue_reading, matches_status, series_status,
                       sort_key, volume_status)


def info(title, status=UNREAD, last_read=0, series=None, volume=None, **kw):
    return VolumeInfo(path=title + ".cbz", key="k:" + title, title=title,
                      series_key=series, volume=volume, status=status,
                      last_read=last_read, **kw)


def test_volume_status():
    assert volume_status(None) == UNREAD
    assert volume_status((0, 20, False)) == UNREAD      # ouvert, pas avance
    assert volume_status((5, 20, False)) == READING
    assert volume_status((19, 20, True)) == FINISHED


def test_series_status():
    assert series_status([FINISHED, FINISHED]) == FINISHED
    assert series_status([FINISHED, UNREAD]) == READING
    assert series_status([UNREAD, UNREAD]) == UNREAD
    assert series_status([]) == UNREAD


def test_matches_status():
    assert matches_status(READING, ALL)
    assert matches_status(READING, READING)
    assert not matches_status(UNREAD, READING)


def test_sort_unknown_values_go_last():
    a = info("A", author="")
    b = info("B", author="Oda")
    assert sorted([a, b], key=lambda i: sort_key("author", i)) == [b, a]
    c = info("C", year=None)
    d = info("D", year=1997)
    assert sorted([c, d], key=lambda i: sort_key("year", i)) == [d, c]
    never = info("E", last_read=0)
    recent = info("F", last_read=200)
    old = info("G", last_read=100)
    assert sorted([never, old, recent], key=lambda i: sort_key("read", i)) == [recent, old, never]


def test_sort_added_most_recent_first():
    a, b = info("A", added=10), info("B", added=20)
    assert sorted([a, b], key=lambda i: sort_key("added", i)) == [b, a]


def test_aggregate_series_info():
    agg = aggregate_series_info("Berserk", [
        info("T1", status=FINISHED, last_read=50, added=5, year=1990, author="Miura"),
        info("T2", status=UNREAD, added=9, year=None)])
    assert agg.last_read == 50 and agg.added == 9
    assert agg.year == 1990 and agg.author == "Miura"
    assert agg.status == READING


def test_continue_reading_in_progress_sorted_by_recency():
    a = info("A", READING, last_read=100)
    b = info("B", READING, last_read=300)
    c = info("C", FINISHED, last_read=500)
    result = continue_reading([a, b, c])
    assert [(i.title, k) for i, k in result] == [("B", "reading"), ("A", "reading")]


def test_continue_reading_proposes_next_volume():
    t1 = info("S1", FINISHED, last_read=100, series="s", volume=1)
    t2 = info("S2", UNREAD, series="s", volume=2)
    t3 = info("S3", UNREAD, series="s", volume=3)
    result = continue_reading([t3, t1, t2])
    assert [(i.title, k) for i, k in result] == [("S2", "next")]


def test_continue_reading_no_next_when_series_has_volume_in_progress():
    t1 = info("S1", FINISHED, last_read=100, series="s", volume=1)
    t2 = info("S2", READING, last_read=200, series="s", volume=2)
    t3 = info("S3", UNREAD, series="s", volume=3)
    result = continue_reading([t1, t2, t3])
    assert [(i.title, k) for i, k in result] == [("S2", "reading")]


def test_continue_reading_series_finished_is_not_proposed():
    t1 = info("S1", FINISHED, last_read=100, series="s", volume=1)
    t2 = info("S2", FINISHED, last_read=200, series="s", volume=2)
    assert continue_reading([t1, t2]) == []


def test_dismissed_item_reappears_after_new_reading():
    a = info("A", READING, last_read=100)
    assert continue_reading([a], dismissed={"k:A": 150}) == []
    a = dataclasses.replace(a, last_read=200)   # relu apres le masquage
    assert len(continue_reading([a], dismissed={"k:A": 150})) == 1


def test_continue_reading_limit():
    items = [info(f"T{i}", READING, last_read=i + 1) for i in range(20)]
    assert len(continue_reading(items, limit=5)) == 5

