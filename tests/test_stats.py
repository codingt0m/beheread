"""Tests de la logique pure des statistiques (stats.py)."""

import datetime as dt
import time

from beheread.core import stats

TODAY = dt.date(2026, 9, 27)


def _stats_with(*sessions, device="pc1"):
    dev = {}
    for date, key, pages, seconds, finished, series in sessions:
        stats.add_session(dev, date, key, pages, seconds, finished, key, series)
    return {"devices": {device: dev}}


def test_add_session_accumulates_per_day_and_volume():
    dev = {}
    stats.add_session(dev, TODAY, "k1", 10, 300, False, "T1", "S")
    stats.add_session(dev, TODAY, "k1", 5, 120, True, "T1", "S")
    rec = dev["days"]["2026-09-27"]["k1"]
    assert rec["pages"] == 15 and rec["seconds"] == 420.0 and rec["finished"] == 1


def test_merged_days_sums_devices():
    s = {"devices": {}}
    for dev_id, pages in (("pc1", 10), ("pc2", 7)):
        dev = s["devices"].setdefault(dev_id, {})
        stats.add_session(dev, TODAY, "k1", pages, 60, False, "T1", "S")
    days = stats.merged_days(s)
    assert days["2026-09-27"]["k1"]["pages"] == 17


def test_streak_counts_consecutive_days_until_yesterday():
    s = _stats_with((TODAY - dt.timedelta(days=1), "a", 5, 60, False, "S"),
                    (TODAY - dt.timedelta(days=2), "a", 5, 60, False, "S"),
                    (TODAY - dt.timedelta(days=4), "a", 5, 60, False, "S"))
    daily = stats.daily_totals(stats.merged_days(s))
    assert stats.streak(daily, TODAY) == 2          # pas encore lu aujourd'hui
    s2 = _stats_with((TODAY, "a", 1, 10, False, "S"))
    assert stats.streak(stats.daily_totals(stats.merged_days(s2)), TODAY) == 1
    assert stats.streak({}, TODAY) == 0


def test_last_n_days_fills_gaps_with_zero():
    s = _stats_with((TODAY, "a", 12, 600, False, "S"))
    rows = stats.last_n_days(stats.daily_totals(stats.merged_days(s)), TODAY, 7)
    assert len(rows) == 7 and rows[-1] == (TODAY, 12, 600.0) and rows[0][1] == 0


def test_top_series_by_time():
    s = _stats_with((TODAY, "a", 10, 600, False, "Berserk"),
                    (TODAY, "b", 30, 300, False, "Pluto"),
                    (TODAY, "c", 5, 900, False, "Berserk"))
    top = stats.top_series(stats.merged_days(s))
    assert [name for name, _s, _p in top] == ["Berserk", "Pluto"]
    assert top[0][1] == 1500


def test_finished_per_month_uses_progress():
    ts = time.mktime(dt.date(2026, 8, 15).timetuple())
    progress = {"k1": {"finished": True, "ts": ts}, "k2": {"finished": False, "ts": ts},
                "k4": {"finished": True, "ts": time.mktime(dt.date(2024, 1, 1).timetuple())}}
    months = stats.finished_per_month(progress, TODAY, 12)
    assert len(months) == 12 and months[-1][0] == dt.date(2026, 9, 1)
    assert dict(months)[dt.date(2026, 8, 1)] == 1
    assert sum(c for _m, c in months) == 1
    assert stats.finished_total(progress) == 2
    assert stats.finished_total(progress, year=2026) == 1


def test_fmt_duration():
    assert stats.fmt_duration(0) == "0 min"
    assert stats.fmt_duration(20) == "moins d'une minute"
    assert stats.fmt_duration(45 * 60) == "45 min"
    assert stats.fmt_duration(3 * 3600 + 5 * 60) == "3 h 05"


def test_nice_ticks():
    assert stats.nice_ticks(0) == [0, 1]
    assert stats.nice_ticks(7) == [0, 2, 4, 6, 8]
    assert stats.nice_ticks(95) == [0, 50, 100]
    ticks = stats.nice_ticks(430)
    assert ticks[0] == 0 and ticks[-1] >= 430 and len(ticks) <= 6
