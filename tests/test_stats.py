"""Tests de la logique pure des statistiques (stats.py)."""

import datetime as dt
import time

from beheread.core import stats

TODAY = dt.date(2026, 9, 27)


def test_day_periods_compare_with_the_same_span_before():
    p = stats.period("30d", TODAY)
    assert (p.start, p.end, p.grain, p.days) == (dt.date(2026, 8, 29), TODAY, "day", 30)
    assert p.previous == (dt.date(2026, 7, 30), dt.date(2026, 8, 28))
    week = stats.period("7d", TODAY)
    assert week.days == 7 and week.previous == (dt.date(2026, 9, 14), dt.date(2026, 9, 20))
    assert stats.period("n'importe quoi", TODAY).key == "30d"


def test_year_period_is_monthly_and_compares_like_for_like():
    p = stats.period("12m", TODAY)
    assert (p.start, p.grain) == (dt.date(2025, 10, 1), "month")
    # meme decoupage un an plus tot, mois en cours arrete au meme jour
    assert p.previous == (dt.date(2024, 10, 1), dt.date(2025, 9, 27))
    leap = stats.period("12m", dt.date(2028, 2, 29))
    assert leap.previous[1] == dt.date(2027, 2, 28)


def test_all_period_starts_at_the_first_day_of_the_journal():
    short = stats.period("all", TODAY, dt.date(2026, 9, 1))
    assert (short.start, short.grain, short.previous) == (dt.date(2026, 9, 1), "day", None)
    long = stats.period("all", TODAY, dt.date(2025, 3, 14))
    assert long.grain == "month" and long.label == "depuis le 14/03/2025"
    empty = stats.period("all", TODAY)
    assert empty.start == empty.end == TODAY


def test_fill_buckets_fills_gaps_with_zero():
    p = stats.period("7d", TODAY)
    buckets = stats.fill_buckets(p, [("2026-09-27", 12, 600.0, 1), ("2026-09-24", 3, 90.0, 0)])
    assert [b.start for b in buckets] == [TODAY - dt.timedelta(days=i) for i in range(6, -1, -1)]
    assert buckets[-1] == stats.Bucket(TODAY, 12, 600.0, 1)
    assert buckets[3].pages == 3 and buckets[0].pages == 0


def test_fill_buckets_by_month():
    p = stats.period("12m", TODAY)
    buckets = stats.fill_buckets(p, [("2026-08", 40, 1200.0, 2)])
    assert len(buckets) == 12
    assert buckets[0].start == dt.date(2025, 10, 1) and buckets[-1].start == dt.date(2026, 9, 1)
    assert buckets[-2].finished == 2


def test_calendar_weeks_run_from_monday_to_sunday():
    p = stats.period("7d", TODAY)                     # du lundi 21 au dimanche 27 sept. 2026
    assert stats.calendar_start(p) == p.start
    days = stats.fill_buckets(p, [])
    assert [[b.start.day for b in week] for week in stats.calendar_weeks(days)] == [
        [21, 22, 23, 24, 25, 26, 27]]
    # periode a cheval sur deux semaines : cases hors periode a None
    days = stats.fill_buckets(stats.period("7d", dt.date(2026, 9, 23)), [])
    weeks = stats.calendar_weeks(days)
    assert [[b and b.start.day for b in week] for week in weeks] == [
        [None, None, None, 17, 18, 19, 20], [21, 22, 23, None, None, None, None]]
    # au-dela de 53 semaines, seules les plus recentes sont affichees
    years = stats.period("all", TODAY, dt.date(2024, 1, 1))
    assert stats.calendar_start(years) == TODAY - dt.timedelta(days=stats.CALENDAR_MAX_DAYS - 1)


def test_heat_levels_follow_quantiles_not_the_maximum():
    values = [0, 600, 900, 1200, 14400]               # une journee exceptionnelle
    thresholds = stats.heat_thresholds(values)
    assert [stats.heat_level(v, thresholds) for v in values] == [0, 1, 2, 3, 4]
    assert stats.heat_level(300, stats.heat_thresholds([300, 300, 300])) == 4   # toutes egales
    assert stats.heat_thresholds([0, 0]) == [] and stats.heat_level(0, []) == 0
    assert stats.heat_level(50, stats.heat_thresholds([50])) == 4


def test_streaks_current_and_best():
    def days(*offsets):
        return [(TODAY - dt.timedelta(days=o)).isoformat() for o in offsets]
    # pas encore lu aujourd'hui : la serie en cours s'arrete hier
    assert stats.streaks(days(1, 2, 4, 5, 6, 7), TODAY) == (2, 4)
    assert stats.streaks(days(0), TODAY) == (1, 1)
    assert stats.streaks(days(3, 4), TODAY) == (0, 2)
    assert stats.streaks([], TODAY) == (0, 0)
    assert stats.streaks(["pas une date", None] + days(0, 1), TODAY) == (2, 2)


def test_top_series_by_time_with_share():
    rows = [("a", "Berserk - Tome 1", "Berserk", 10, 600.0, 0),
            ("b", "Pluto - Tome 1", "Pluto", 30, 500.0, 1),
            ("c", "Berserk - Tome 2", "berserk", 5, 900.0, 1),   # casse differente : meme serie
            ("d", "Vide", "Vide", 0, 0.0, 1)]                    # fin de tome sans lecture
    top = stats.top_series(rows)
    assert [(s.name, s.seconds, s.pages, s.finished) for s in top] == [
        ("Berserk", 1500.0, 15, 1), ("Pluto", 500.0, 30, 1)]
    assert top[0].share == 0.75
    assert len(stats.top_series(rows, n=1)) == 1


def test_top_series_follows_the_current_library_grouping():
    rows = [("a", "Tome 1", "Ancien nom", 10, 600.0, 0),
            ("b", "Tome 2", "Nouveau nom", 10, 300.0, 0),
            ("x", "Disparu", "Autre", 5, 100.0, 0)]
    library = {"a": ("serie", "Nom affiché"), "b": ("serie", "Nom affiché")}
    top = stats.top_series(rows, resolve=library.get)
    # la serie renommee n'est pas scindee ; le tome inconnu garde son nom d'origine
    assert [(s.name, s.seconds) for s in top] == [("Nom affiché", 900.0), ("Autre", 100.0)]


def test_legacy_journal_pages_are_bounded_by_reading_time():
    section = {"name": "PC", "updated": 5, "days": {
        "2026-09-27": {"k1": {"pages": 131, "seconds": 6.0, "finished": 0,
                              "title": "T", "series": "S"},
                       "k2": {"pages": 20, "seconds": 400.0, "finished": 1},
                       "k3": {"pages": 9, "seconds": 0, "finished": 0}},   # feuillete : rien
        "pas-un-jour": {"k4": {"pages": 3, "seconds": 60}},
        "2026-09-28": "abime"}}
    rows = list(stats.journal_rows("pc", section))
    assert rows == [("2026-09-27", "pc", "k1", 6, 6.0, 1, 0, "T", "S"),
                    ("2026-09-27", "pc", "k2", 20, 400.0, 1, 1, "", "")]
    assert list(stats.journal_rows("pc", "abime")) == []


def test_current_journal_roundtrips_unchanged():
    section = stats.journal_section("PC", 12.0, [
        ("2026-09-27", "k1", 3, 2.0, 2, 1, "T", "S")])   # 3 pages en 2 s : regles actuelles
    assert section["rules"] == stats.JOURNAL_RULES
    assert list(stats.journal_rows("pc", section)) == [
        ("2026-09-27", "pc", "k1", 3, 2.0, 2, 1, "T", "S")]


def test_finished_before_journal_uses_last_read_date():
    def ts(*ymd):
        return time.mktime(dt.date(*ymd).timetuple())
    progress = {"k1": {"finished": True, "ts": ts(2026, 8, 15)},
                "k2": {"finished": False, "ts": ts(2026, 8, 15)},
                "k3": {"finished": True, "ts": ts(2026, 9, 28)},   # depuis le journal : ignore
                "k4": {"finished": True}, "k5": "abime"}
    assert stats.finished_before_journal(progress, dt.date(2026, 9, 27)) == [("2026-08-15", "k1")]


def test_fmt_duration():
    assert stats.fmt_duration(0) == "0 min"
    assert stats.fmt_duration(20) == "moins d'une minute"
    assert stats.fmt_duration(45 * 60) == "45 min"
    assert stats.fmt_duration(3 * 3600 + 5 * 60) == "3 h 05"
    assert stats.fmt_duration(3 * 3600) == "3 h 00"
    assert stats.fmt_duration(3 * 3600, compact=True) == "3 h"
    assert stats.fmt_duration(28, compact=True) == "28 s"
    assert stats.fmt_duration(0, compact=True) == "0 min"


def test_nice_ticks():
    assert stats.nice_ticks(0) == [0, 1]
    assert stats.nice_ticks(7) == [0, 2, 4, 6, 8]
    assert stats.nice_ticks(95) == [0, 50, 100]
    ticks = stats.nice_ticks(430)
    assert ticks[0] == 0 and ticks[-1] >= 430 and len(ticks) <= 6


def test_time_ticks_are_round_durations():
    assert stats.time_ticks(0) == [0, 60]
    assert stats.time_ticks(50 * 60) == [0, 900, 1800, 2700, 3600]      # pas de 15 min
    assert stats.time_ticks(3.5 * 3600) == [0, 3600, 7200, 10800, 14400]
    days = stats.time_ticks(9 * 86400)
    assert days[-1] >= 9 * 86400 and days[1] % 86400 == 0
