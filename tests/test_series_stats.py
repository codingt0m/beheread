"""Tests des statistiques d'une serie (series_stats.py, ReadingLog.series_rows)."""

import datetime as dt

import pytest

from beheread.core import series_stats as ss
from beheread.core import stats, units
from beheread.infra.database import Database
from beheread.infra.reading_log import ReadingLog

TODAY = dt.date(2026, 10, 24)


def _day(offset):
    return TODAY - dt.timedelta(days=offset)


@pytest.fixture
def log(tmp_path):
    db = Database(tmp_path / "t.db")
    yield ReadingLog(db)
    db.close()


def _add(log, day, volume, pages, seconds, finished=False, series="Berserk", device="pc1",
         title=None):
    log.add(device, device.upper(), day, volume, pages, seconds, finished, title or volume,
            series, 100.0)


def _holdings(*items, extra=()):
    return ss.SeriesHoldings("berserk", "Berserk", "Kentaro Miura", tuple(items), extra)


def test_series_rows_by_volume_and_by_series_name(log):
    _add(log, _day(3), "b1", 40, 800, finished=True, series="")
    _add(log, _day(1), "b2", 20, 400, device="tab", title="Berserk - Tome 2")
    _add(log, _day(0), "autre", 99, 999, series="Pluto")
    assert log.series_names() == ["Berserk", "Pluto"]
    assert log.series_rows(["b1"], ["Berserk"]) == [
        (_day(3).isoformat(), "PC1", "b1", 40, 800.0, 1, 1, "b1"),
        (_day(1).isoformat(), "TAB", "b2", 20, 400.0, 1, 0, "Berserk - Tome 2")]
    assert log.series_rows([]) == []
    # au-dela de la limite de parametres de SQLite : par paquets
    assert len(log.series_rows([f"x{i}" for i in range(1200)] + ["b1"])) == 1


def test_report_counts_only_reading_and_survives_deleted_files(log):
    # tome 1 : survole puis termine (marque lu) ; tome 2 : lu d'une traite
    # dans un fichier remplace depuis ; tome 3 : lu en deux jours ; tome 4 :
    # virtuel, commence par l'un de ses chapitres ; tome 6 : supprime ; un
    # chapitre deja dans un tome ; un tome range depuis dans une autre serie
    _add(log, _day(20), "v1", 5, 30, finished=True)
    _add(log, _day(3), "v2old", 190, 1800, finished=True, title="Berserk - Tome 2")
    _add(log, _day(3), "v3", 60, 500)
    _add(log, _day(3), "v3", 50, 500)                   # deuxieme seance du jour
    _add(log, _day(1), "v3", 90, 1000, finished=True)
    _add(log, _day(1), "c10", 30, 300, title="Berserk Chapitre 10")
    _add(log, _day(2), "v6gone", 200, 2000, finished=True, title="Berserk - Tome 6")
    _add(log, _day(1), "c99", 15, 100, title="Berserk Chapitre 99")
    _add(log, _day(1), "moved", 50, 500, title="Berserk - Tome 7")
    _add(log, _day(0), "p1", 200, 9000, series="Pluto")
    h = _holdings(
        ss.SeriesItem(1, units.VOLUME, "v1", ss.FINISHED, 199, 200),
        ss.SeriesItem(2, units.VOLUME, "v2new", ss.FINISHED, 199, 200),
        ss.SeriesItem(3, units.VOLUME, "v3", ss.FINISHED, 199, 200),
        ss.SeriesItem(4, units.VOLUME, "virt", ss.READING, 30, 60,
                      aliases=("c10", "c11"), covers=(10, 11)),
        ss.SeriesItem(5, units.VOLUME, "v5", ss.UNREAD, 0, 200),
        extra=("c99",))
    owner = {"moved": "pluto", "p1": "pluto"}.get
    resolve = {"v1": ("berserk", "Berserk"), "p1": ("pluto", "Pluto")}.get
    r = ss.build_series_report(log, h, TODAY, resolve, library_pace=10.0, owner=owner)

    assert ss.series_seconds(log, h, owner) == r.seconds == 6230.0
    assert (r.pages, r.active_days, r.sessions) == (640, 3, 7)
    assert (r.first_day, r.last_day) == (_day(3), _day(1))   # le coup d'oeil du J-20 n'y est pas
    # le tome supprime reprend sa place, termine
    assert [(v.item.number, v.item.status) for v in r.volumes] == [
        (1, "finished"), (2, "finished"), (3, "finished"), (4, "reading"), (5, "unread"),
        (6, "finished")]
    stat = {v.item.number: v for v in r.volumes}
    assert [n for n, v in stat.items() if v.read_here] == [2, 3, 6]
    assert [n for n, v in stat.items() if v.one_sitting] == [2, 6]
    assert stat[2].seconds == 1800 and stat[4].seconds == 300 and stat[3].sessions == 2 + 1
    assert r.finished == 4 and r.median_seconds() == 2000
    assert r.pace == pytest.approx(6200 / 635)
    # reste : 30 pages du tome 4 et 200 du tome 5, au rythme de la serie
    assert r.remaining_items == 2 and r.remaining_seconds == pytest.approx(230 * 6200 / 635)
    assert r.remaining_days == pytest.approx(r.remaining_seconds / (6200 / 3))

    days = [e for e in r.journal if isinstance(e, ss.DayEntry)]
    assert [e.day for e in days] == [_day(1), _day(2), _day(3)]
    assert [i.number for i in days[0].finished] == [3] and [i.number for i in days[0].started] == [4]
    assert [i.number for i in days[1].finished] == [6] and days[1].started == ()
    assert [i.number for i in days[2].finished] == [2] and [i.number for i in days[2].started] == [3]
    assert r.journal[-1] == ss.GlanceRun(_day(20), _day(20), 1, 30.0)
    assert r.best_day.day == _day(3) and r.best_day.seconds == 2800
    assert r.session_seconds == pytest.approx(6200 / 7)
    assert r.rank == 2 and r.devices == [("PC1", 6230.0)]


def test_glance_days_are_grouped_and_unread_series_is_empty(log):
    _add(log, _day(9), "b1", 3, 20)
    _add(log, _day(5), "b1", 2, 10)
    h = _holdings(ss.SeriesItem(1, units.VOLUME, "b1", ss.UNREAD, 0, 180))
    r = ss.build_series_report(log, h, TODAY, None, library_pace=12.0)
    assert r.journal == [ss.GlanceRun(_day(9), _day(5), 2, 30.0)]
    assert r.active_days == 0 and r.sessions == 0 and r.pace is None and r.best_day is None
    assert (r.first_day, r.last_day) == (_day(9), _day(5))
    assert r.remaining_seconds == 180 * 12.0          # repli sur le rythme moyen
    assert r.remaining_days is None and r.read_here == [] and r.median_seconds() == 0

    empty = ss.build_series_report(log, ss.SeriesHoldings("x", "Neuve"), TODAY)
    assert empty.seconds == 0 and empty.journal == [] and empty.first_day is None


def test_items_follow_reading_order():
    items = [ss.SeriesItem(12, units.CHAPTER), ss.SeriesItem(2), ss.SeriesItem(None),
             ss.SeriesItem(1)]
    assert [(i.number, i.unit) for i in sorted(items, key=ss.item_order)] == [
        (None, units.VOLUME), (1, units.VOLUME), (2, units.VOLUME), (12, units.CHAPTER)]


def test_series_ranking_counts_finished_chapters_apart():
    rows = [("v1", "Berserk - Tome 1", "Berserk", 200, 3000.0, 1),
            ("c1", "Chainsaw Man Chapitre 211", "Chainsaw Man", 20, 300.0, 2),
            ("c2", "Chainsaw Man Chapitre 212", "Chainsaw Man", 20, 300.0, 1)]
    ranked = {s.name: (s.finished, s.finished_chapters) for s in stats.top_series(rows)}
    assert ranked == {"Berserk": (1, 0), "Chainsaw Man": (3, 3)}


def test_weekday_averages_count_days_without_reading():
    days = stats.fill_range(dt.date(2026, 10, 5), dt.date(2026, 10, 18), "day",
                            [("2026-10-05", 10, 600.0, 0), ("2026-10-11", 5, 300.0, 0)])
    avg = stats.weekday_averages(days)
    assert avg[0] == (300.0, 2) and avg[6] == (150.0, 2) and avg[3] == (0.0, 2)
