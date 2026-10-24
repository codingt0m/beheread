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


def _add(log, day, volume, pages, seconds, finished=False, series="Berserk", device="pc1"):
    log.add(device, device.upper(), day, volume, pages, seconds, finished, volume, series, 100.0)


def _holdings(*items, published=None):
    return ss.SeriesHoldings("berserk", "Berserk", "Kentaro Miura", published, tuple(items))


def test_series_rows_cover_every_volume_with_device_names(log):
    _add(log, _day(3), "b1", 40, 800, finished=True)
    _add(log, _day(1), "b2", 20, 400, device="tab")
    _add(log, _day(0), "autre", 99, 999)
    assert log.series_rows(["b2", "b1", "b1"]) == [
        (_day(3).isoformat(), "PC1", "b1", 40, 800.0, 1, 1),
        (_day(1).isoformat(), "TAB", "b2", 20, 400.0, 1, 0)]
    assert log.series_rows([]) == []
    # au-dela de la limite de parametres de SQLite : par paquets
    assert len(log.series_rows([f"x{i}" for i in range(1200)] + ["b1"])) == 1


def test_report_crosses_the_journal_with_the_library(log):
    # tome 1 lu en deux jours, sur deux appareils ; tome 2 en cours ; tome 3
    # non lu ; tome 4 manquant ; « vieux » termine avant le journal
    _add(log, _day(40), "b1", 100, 2000)
    _add(log, _day(39), "b1", 100, 2400, finished=True, device="tab")
    _add(log, _day(2), "b2", 50, 1000)
    _add(log, _day(0), "autre", 200, 9000, series="Pluto")
    h = _holdings(
        ss.SeriesItem(0, units.VOLUME, "vieux", ss.FINISHED, 199, 200),
        ss.SeriesItem(1, units.VOLUME, "b1", ss.FINISHED, 199, 200),
        ss.SeriesItem(2, units.VOLUME, "b2", ss.READING, 50, 200),
        ss.SeriesItem(3, units.VOLUME, "b3", ss.UNREAD, 0, 0),
        ss.SeriesItem(4, units.VOLUME, None, ss.MISSING),
        published=4)
    names = {"vieux": ("berserk", "Berserk"), "b1": ("berserk", "Berserk"),
             "b2": ("berserk", "Berserk"), "autre": ("pluto", "Pluto")}
    r = ss.build_series_report(log, h, TODAY, names.get, pace=20.0, library_pace=10.0)

    t = r.totals
    assert (t.pages, t.seconds, t.sessions, t.finished, t.active_days) == (250, 5400.0, 3, 1, 3)
    assert (r.first_day, r.last_day) == (_day(40), _day(2))
    assert (r.finished, r.owned) == (2, 4)
    # « vieux » est termine sans date : la progression part de 1
    assert r.base == 1
    assert [(d, n, v.item.number) for d, n, v in r.progression] == [(_day(39), 2, 1)]
    # reste : 150 pages du tome 2 au rythme de la serie ; le tome 3 n'a pas
    # de nombre de pages connu
    assert (r.remaining_items, r.remaining_seconds, r.unknown_pages) == (2, 3000.0, 1)
    # une fin il y a 39 jours : 2 tomes en 90 jours / 1 = 180 jours
    assert r.recent_finished == 1 and r.projected_end == TODAY + dt.timedelta(days=180)
    assert r.rank == 2 and r.share == pytest.approx(5400 / 14400)
    assert r.best_day.start == _day(39) and r.best_day.seconds == 2400
    assert r.devices == [("PC1", 3000.0), ("TAB", 2400.0)]
    assert len(r.months) == ss.SPARK_MONTHS and r.months[-1].start == dt.date(2026, 10, 1)
    assert [b.seconds for b in r.months[-2:]] == [4400.0, 1000.0]   # sept. (b1 a J-39 et J-40) puis oct.
    stat = {v.item.number: v for v in r.volumes}
    assert stat[1].seconds == 4400 and stat[1].finished_on == _day(39)
    assert stat[2].finished_on is None and stat[4].pages == 0


def test_unread_series_and_projection_rules(log):
    h = _holdings(ss.SeriesItem(1, units.VOLUME, "b1", ss.UNREAD, 0, 180))
    r = ss.build_series_report(log, h, TODAY, None, pace=None, library_pace=12.0)
    assert r.totals.empty and r.first_day is None and r.rank is None
    assert r.remaining_seconds == 180 * 12.0   # repli sur le rythme moyen
    assert r.projected_end is None and r.best_day is None and r.devices == []
    # pas de fin recente : pas de projection ; rien a lire : pas de projection
    assert ss.projected_end(5, 0, TODAY) is None and ss.projected_end(0, 3, TODAY) is None
    assert ss.projected_end(3, 9, TODAY) == TODAY + dt.timedelta(days=30)


def test_items_follow_reading_order():
    items = [ss.SeriesItem(12, units.CHAPTER), ss.SeriesItem(2), ss.SeriesItem(None),
             ss.SeriesItem(1, status=ss.MISSING)]
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
