"""Tests de la politique du cache hors ligne (offline_cache.py) : tomes N,
N+1 et N-1 des series en cours, remplissage du budget par priorite."""

from beheread.core.library_model import FINISHED, READING, UNREAD
from beheread.core.models import VolumeInfo
from beheread.core.offline_cache import volumes_to_keep


def info(title, status=UNREAD, last_read=0, series=None, volume=None, **kw):
    return VolumeInfo(path=title + ".cbz", key="k:" + title, title=title,
                      series_key=series, volume=volume, status=status,
                      last_read=last_read, **kw)


def series(name, statuses, last_read=None):
    """Tomes 1..n d'une serie ; `last_read` : {numero: horodatage}."""
    last_read = last_read or {}
    return [info(f"{name} {n}", status=s, series=name, volume=n, last_read=last_read.get(n, 0))
            for n, s in enumerate(statuses, start=1)]


def test_reading_volume_and_its_neighbours():
    vols = series("Berserk", [FINISHED, FINISHED, READING, UNREAD, UNREAD],
                  {1: 10, 2: 20, 3: 30})
    assert volumes_to_keep(vols) == ["k:Berserk 3", "k:Berserk 4", "k:Berserk 2"]


def test_next_volume_after_a_finished_one():
    vols = series("Pluto", [FINISHED, UNREAD, UNREAD], {1: 10})
    # N = tome 2 (le suivant a lire), N+1 = tome 3, N-1 = tome 1
    assert volumes_to_keep(vols) == ["k:Pluto 2", "k:Pluto 3", "k:Pluto 1"]


def test_first_volume_has_no_previous():
    vols = series("Nana", [READING, UNREAD], {1: 5})
    assert volumes_to_keep(vols) == ["k:Nana 1", "k:Nana 2"]


def test_untouched_series_are_not_kept():
    assert volumes_to_keep(series("Akira", [UNREAD, UNREAD, UNREAD])) == []


def test_lone_volume_without_series():
    assert volumes_to_keep([info("One shot", READING, last_read=5)]) == ["k:One shot"]


def test_current_volumes_of_all_series_come_before_neighbours():
    a = series("A", [FINISHED, READING, UNREAD], {1: 1, 2: 100})   # lue le plus recemment
    b = series("B", [FINISHED, READING, UNREAD], {1: 1, 2: 50})
    assert volumes_to_keep(a + b) == ["k:A 2", "k:B 2", "k:A 3", "k:B 3", "k:A 1", "k:B 1"]


def test_budget_skips_what_does_not_fit_but_keeps_smaller_ones():
    a = series("A", [FINISHED, READING, UNREAD], {1: 1, 2: 100})
    sizes = {"k:A 2": 400, "k:A 3": 700, "k:A 1": 200}
    # 400 + 700 > 1000 : le tome 3 est saute, le tome 1 (200) tient encore
    assert volumes_to_keep(a, sizes, budget=1000) == ["k:A 2", "k:A 1"]


def test_unknown_size_is_kept_without_counting():
    a = series("A", [FINISHED, READING, UNREAD], {1: 1, 2: 100})
    assert volumes_to_keep(a, {"k:A 2": 900}, budget=1000) == ["k:A 2", "k:A 3", "k:A 1"]


def test_dismissed_series_is_not_current():
    vols = series("Monster", [FINISHED, READING, UNREAD], {1: 10, 2: 20})
    assert volumes_to_keep(vols, dismissed={"k:Monster 2": 30}) == []
