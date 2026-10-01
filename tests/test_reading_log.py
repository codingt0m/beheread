"""Tests du journal de lecture (reading_log.py) : ecriture d'une seance,
agregats SQL par periode, sauvegarde, et migration de l'ancien journal."""

import datetime as dt
import json
import sqlite3

import pytest

from beheread.core import stats
from beheread.infra import database
from beheread.infra.database import SCHEMA_VERSION, Database
from beheread.infra.reading_log import ReadingLog

TODAY = dt.date(2026, 9, 27)


def _day(offset):
    return TODAY - dt.timedelta(days=offset)


@pytest.fixture
def log(tmp_path):
    db = Database(tmp_path / "t.db")
    yield ReadingLog(db)
    db.close()


def _add(log, day, volume, pages, seconds, finished=False, series="S", device="pc1"):
    log.add(device, device.upper(), day, volume, pages, seconds, finished, volume, series, 100.0)


def test_sessions_accumulate_per_day_and_volume(log):
    _add(log, TODAY, "k1", 10, 300)
    _add(log, TODAY, "k1", 5, 120.04, finished=True)
    _add(log, TODAY, "k1", 0, 0, finished=True)       # fin de tome seule : pas une seance
    rows = log._query("SELECT pages, seconds, sessions, finished FROM reading_log")
    assert rows == [(15, 420.0, 2, 2)]


def test_totals_are_bounded_to_the_period_and_sum_devices(log):
    _add(log, TODAY, "k1", 10, 300, device="pc1")
    _add(log, TODAY, "k1", 7, 60, device="pc2")
    _add(log, _day(3), "k2", 4, 100, finished=True)
    _add(log, _day(3), "k3", 0, 0, finished=True)     # jour sans page lue : pas un jour de lecture
    _add(log, _day(40), "k1", 99, 999)                # hors periode
    t = log.totals(_day(29), TODAY)
    assert t == stats.Totals(pages=21, seconds=460.0, sessions=3, finished=2,
                             active_days=2, volumes=2)
    assert log.totals(_day(400), _day(300)).empty


def test_buckets_by_day_and_by_month(log):
    _add(log, dt.date(2026, 9, 27), "k1", 10, 300)
    _add(log, dt.date(2026, 9, 2), "k2", 5, 100, finished=True)
    _add(log, dt.date(2026, 8, 30), "k1", 1, 10)
    start = dt.date(2026, 8, 1)
    assert log.buckets(start, TODAY) == [("2026-08-30", 1, 10.0, 0), ("2026-09-02", 5, 100.0, 1),
                                         ("2026-09-27", 10, 300.0, 0)]
    assert log.buckets(start, TODAY, "month") == [("2026-08", 1, 10.0, 0),
                                                  ("2026-09", 15, 400.0, 1)]


def test_volumes_carry_their_latest_title_and_series(log):
    log.add("pc1", "PC1", _day(5), "k1", 10, 300, False, "Vieux titre", "Vieux nom", 1.0)
    log.add("pc1", "PC1", _day(1), "k1", 5, 100, True, "Titre", "Nom", 2.0)
    log.add("pc1", "PC1", _day(2), "k2", 3, 50, False, "Autre", "Autre", 3.0)
    assert log.volumes(_day(29), TODAY) == [("k1", "Titre", "Nom", 15, 400.0, 1),
                                            ("k2", "Autre", "Autre", 3, 50.0, 0)]


def test_report_assembles_period_comparison_and_streaks(log):
    for offset in (0, 1, 2, 10, 11, 12, 13):
        _add(log, _day(offset), "k1", 10, 600, series="Berserk")
    _add(log, _day(35), "k2", 30, 900, finished=True, series="Pluto")
    report = stats.build_report(log, "30d", TODAY)
    assert report.totals.pages == 70 and report.totals.active_days == 7
    assert report.previous.pages == 30 and report.previous.finished == 1
    assert len(report.buckets) == 30 and report.buckets[-1].seconds == 600.0
    assert (report.streak, report.best_streak) == (3, 4)
    assert [(s.name, s.share) for s in report.series] == [("Berserk", 1.0)]
    assert report.first_day == _day(35) and report.first_session == _day(35)
    assert len(report.calendar) == 30 and report.calendar[-1].pages == 10
    assert report.finished_volumes == []

    everything = stats.build_report(log, "all", TODAY)
    assert everything.previous is None and everything.totals.pages == 100
    assert everything.period.start == _day(35) and len(everything.buckets) == 36
    assert everything.finished_volumes == [(_day(35), "k2", "k2", "Pluto")]


def test_finished_volumes_are_listed_most_recent_first(log):
    _add(log, _day(9), "k1", 10, 300, finished=True)
    _add(log, _day(2), "k2", 10, 300, finished=True)
    _add(log, _day(1), "k3", 10, 300)                 # lu, pas termine
    _add(log, _day(50), "k4", 10, 300, finished=True)  # hors periode
    assert [row[1] for row in log.finished(_day(29), TODAY, 6)] == ["k2", "k1"]
    assert [row[1] for row in log.finished(_day(29), TODAY, 1)] == ["k2"]
    assert log.first_day(sessions_only=True) == _day(50)


def test_empty_journal_gives_an_empty_report(log):
    report = stats.build_report(log, "12m", TODAY)
    assert report.totals.empty and report.first_day is None and report.series == []
    assert len(report.buckets) == 12 and (report.streak, report.best_streak) == (0, 0)


def test_export_import_never_double_counts(log, tmp_path):
    _add(log, TODAY, "k1", 10, 300, device="pc1")
    exported = json.loads(json.dumps(log.export()))
    assert exported["devices"]["pc1"]["days"][TODAY.isoformat()]["k1"]["pages"] == 10
    assert exported["devices"]["pc1"]["rules"] == stats.JOURNAL_RULES

    other_db = Database(tmp_path / "autre.db")
    other = ReadingLog(other_db)
    for _ in range(2):   # meme sauvegarde importee deux fois
        other.replace_devices(exported["devices"])
    assert other.totals(TODAY, TODAY).pages == 10
    assert other.devices() == {"pc1": 100.0}
    other_db.close()


def test_schema_v1_journal_is_migrated_and_database_backed_up(tmp_path):
    """Base d'une version precedente : le journal JSON par appareil est repris
    dans la table, ses pages feuilletees sont ecartees, et une copie de la
    base d'origine est conservee."""
    path = tmp_path / "beheread.db"
    con = sqlite3.connect(str(path))
    for sql in database.MIGRATIONS[1]:
        con.execute(sql)
    con.execute("PRAGMA user_version = 1")
    section = {"name": "PC-SALON", "updated": 42.0, "days": {"2026-09-27": {
        "c1:a": {"pages": 131, "seconds": 6.0, "finished": 0, "title": "A", "series": "S"},
        "c1:b": {"pages": 20, "seconds": 400.0, "finished": 1, "title": "B", "series": "S"}}}}
    con.execute("INSERT INTO stats_devices(key, value) VALUES('pc', ?)", (json.dumps(section),))
    con.execute("INSERT INTO stats_devices(key, value) VALUES('casse', '{pas du json')")
    con.commit()
    con.close()

    db = Database(path)
    assert db.version == SCHEMA_VERSION
    log = ReadingLog(db)
    assert log.totals(TODAY, TODAY) == stats.Totals(pages=26, seconds=406.0, sessions=2,
                                                    finished=1, active_days=1, volumes=2)
    assert log.devices() == {"pc": 42.0}
    # l'ancien journal n'est pas detruit
    assert db.conn.execute("SELECT count(*) FROM stats_devices").fetchone()[0] == 2
    db.close()

    backup = sqlite3.connect(str(tmp_path / "beheread-v1.bak"))
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
    assert backup.execute("SELECT count(*) FROM stats_devices").fetchone()[0] == 2
    backup.close()

    Database(path).close()   # reouverture : ni nouvelle migration ni nouvelle copie
