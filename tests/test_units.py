"""Tomes et chapitres d'une serie (core/units.py)."""

from beheread.core import units
from beheread.core.units import (
    AUTO,
    CHAPTER,
    CHAPTERS,
    VOLUME,
    VOLUMES,
    SeriesCounts,
    classifier,
    count_text,
    missing_chapters,
    next_in_series,
    progress_text,
    series_counts,
)
from beheread.i18n import set_language


def setup_module():
    set_language("fr")


# --------------------------------------------------------------- classification

def test_unmarked_numbers_are_volumes_next_to_explicit_volumes_and_chapters():
    # Chainsaw Man : « T01 », « Chainsaw Man 12 » (tome sans marqueur), « Chapitre 211 »
    unit = classifier(["volume", "bare", "chapter"])
    assert unit("volume") == VOLUME
    assert unit("bare") == VOLUME
    assert unit("chapter") == CHAPTER


def test_unmarked_numbers_are_chapters_in_a_chapter_only_series():
    unit = classifier(["chapter", "bare"])
    assert unit("bare") == CHAPTER


def test_unmarked_numbers_alone_are_volumes():
    assert classifier(["bare"])("bare") == VOLUME


def test_forced_nature_applies_to_every_numbered_file():
    as_chapters = classifier(["volume", "bare", "chapter"], CHAPTERS)
    assert {as_chapters(k) for k in ("volume", "bare", "chapter")} == {CHAPTER}
    as_volumes = classifier(["chapter"], VOLUMES)
    assert as_volumes("chapter") == VOLUME


def test_cycles_ranges_and_unnumbered_files_keep_their_nature():
    for nature in (AUTO, VOLUMES, CHAPTERS):
        unit = classifier(["volume", "cycle", "range", None], nature)
        assert unit("cycle") == "cycle" and unit("range") == "range" and unit(None) is None


def test_label_kind_follows_the_unit():
    assert units.label_kind("bare", CHAPTER) == "chapter"
    assert units.label_kind("chapter", VOLUME) == "volume"
    assert units.label_kind("cycle", None) == "cycle"


# --------------------------------------------------------------- ordre de lecture

def test_chapters_come_after_every_volume_whatever_their_numbers():
    items = [("ch3", CHAPTER, 3), ("t1", VOLUME, 1), ("t5", VOLUME, 5), ("ch1", CHAPTER, 1)]
    ordered = sorted(items, key=lambda i: units.order_key(i[1], i[2]))
    assert [i[0] for i in ordered] == ["t1", "t5", "ch1", "ch3"]


def test_next_item_goes_from_last_volume_to_first_chapter():
    items = [("t21", VOLUME, 21), ("t22", VOLUME, 22), ("c211", CHAPTER, 211),
             ("c212", CHAPTER, 212)]
    assert next_in_series("t21", items) == "t22"
    assert next_in_series("t22", items) == "c211"
    assert next_in_series("c211", items) == "c212"
    assert next_in_series("c212", items) is None


def test_a_chapter_is_never_followed_by_a_volume():
    # chapitre 5 et tome 6 : l'ancien enchainement par numero passait au tome
    items = [("c5", CHAPTER, 5), ("t6", VOLUME, 6), ("c6", CHAPTER, 6)]
    assert next_in_series("c5", items) == "c6"
    assert next_in_series("t6", items) == "c5"


def test_find_next_volume_goes_from_last_volume_to_chapters(tmp_path):
    from beheread.infra.archive import find_next_volume
    for name in ("Chainsaw Man T21", "Chainsaw Man T22", "Chainsaw Man 12",
                 "Chainsaw Man Chapitre 5", "Chainsaw Man Chapitre 211"):
        (tmp_path / f"{name}.cbz").write_bytes(b"PK\x03\x04dummy")
    nxt = lambda n: find_next_volume(str(tmp_path / f"{n}.cbz"))   # noqa: E731
    assert nxt("Chainsaw Man 12").endswith("T21.cbz")
    assert nxt("Chainsaw Man T22").endswith("Chapitre 5.cbz")
    assert nxt("Chainsaw Man Chapitre 5").endswith("Chapitre 211.cbz")


def test_bonus_chapter_is_read_in_order():
    items = [("c12", CHAPTER, 12), ("c12.5", CHAPTER, 12.5), ("c13", CHAPTER, 13)]
    assert next_in_series("c12", items) == "c12.5"


def test_cycles_chain_only_with_cycles():
    items = [("cy1", "cycle", 1), ("t2", VOLUME, 2), ("cy2", "cycle", 2), ("t1", VOLUME, 1)]
    assert next_in_series("cy1", items) == "cy2"
    assert next_in_series("t1", items) == "t2"
    assert next_in_series("cy2", items) is None


def test_unnumbered_or_unknown_items_have_no_next():
    items = [("t1", VOLUME, 1), ("x", None, None)]
    assert next_in_series("x", items) is None
    assert next_in_series("unknown", items) is None


# --------------------------------------------------------------- avancement

def test_counts_split_volumes_and_chapters():
    c = series_counts([(VOLUME, 1, True, True), (VOLUME, 2, False, False),
                       (CHAPTER, 211, True, True), (CHAPTER, 212, False, True),
                       (CHAPTER, 213, False, False), (None, None, False, False)])
    assert (c.volumes, c.chapters, c.volumes_read, c.chapters_read) == (3, 3, 1, 1)
    assert (c.first_chapter, c.last_chapter, c.current_chapter) == (211, 213, 212)
    assert (c.total, c.read) == (6, 2)


def test_progress_text_of_a_volume_only_series_is_unchanged():
    assert progress_text(SeriesCounts(volumes=41)) == "41 tomes"
    assert progress_text(SeriesCounts(volumes=41, volumes_read=12)) == "12/41 tomes lus"
    assert progress_text(SeriesCounts(volumes=3, volumes_read=3)) == "Série terminée"


def test_progress_text_of_a_chapter_only_series():
    assert progress_text(SeriesCounts(chapters=40)) == "40 chapitres"
    assert progress_text(SeriesCounts(chapters=40, chapters_read=12)) == "12/40 chapitres lus"


def test_progress_text_of_a_mixed_series_follows_the_reading_path():
    base = dict(volumes=22, chapters=22, first_chapter=211, last_chapter=232)
    assert progress_text(SeriesCounts(**base)) == "22 tomes + 22 chapitres"
    assert (progress_text(SeriesCounts(volumes_read=6, **base))
            == "Tome 6/22 · puis ch. 211 à 232")
    assert (progress_text(SeriesCounts(volumes_read=22, current_chapter=213, chapters_read=2,
                                       **base))
            == "Tomes lus · chapitre 213 en cours")
    assert (progress_text(SeriesCounts(volumes_read=22, chapters_read=2, **base))
            == "Tomes lus · 2/22 chapitres")


def test_count_text():
    assert count_text(44, 0) == "44 tomes"
    assert count_text(22, 22) == "22 tomes · 22 chapitres"
    assert count_text(0, 23) == "23 chapitres"
    assert count_text(0, 0) == "0 tome"


# --------------------------------------------------------------- manquants

def test_missing_chapters_of_a_chapter_only_series_start_at_one():
    assert missing_chapters([3, 4, 6], start=1) == [1, 2, 5]


def test_missing_chapters_of_a_mixed_series_start_at_the_first_owned_chapter():
    assert missing_chapters([211, 212, 214, 214.5]) == [213]
    assert missing_chapters([]) == []


def test_missing_chapters_start_right_after_the_last_volume_when_known():
    ranges = {"21": [181, 189], "22": [190, 210], "23": [211, 220]}
    assert units.coverage_end([21, 22], ranges) == 210
    assert units.coverage_end([22], {}) is None
    # decoupage lacunaire : le dernier tome possede n'y est pas
    assert units.coverage_end([20, 21, 22], {"20": [176, 203]}) is None
    assert missing_chapters([213, 214], start=211) == [211, 212]


# --------------------------------------------------------------- chapitres redondants

def test_chapters_inside_an_owned_volume_are_covered():
    ranges = {"42": [374, 380], "43": [381, 390]}
    assert units.covered_chapters([379, 383, 386], [41, 42], ranges) == {379}
    assert units.covered_chapters([383], [42, 43], ranges) == {383}
    assert units.covered_chapters([383], [43], None) == set()


def test_covered_chapters_leave_the_reading_path_and_the_counts():
    items = [("t22", VOLUME, 22), ("c205", units.COVERED, 205), ("c211", CHAPTER, 211)]
    assert next_in_series("t22", items) == "c211"
    assert next_in_series("c205", items) is None
    c = series_counts([(VOLUME, 22, True, True), (units.COVERED, 205, False, False),
                       (CHAPTER, 211, False, False)])
    assert (c.volumes, c.chapters, c.first_chapter) == (1, 1, 211)
    assert units.label_kind("chapter", units.COVERED) == "chapter"
    assert units.is_chapter(units.COVERED) and not units.is_chapter(VOLUME)


def test_volume_of_a_chapter():
    ranges = {"42": [365, 373], "43": [374, 383]}
    assert units.volume_of(383, ranges) == 43
    assert units.volume_of(373.5, ranges) is None
    assert units.volume_of(384, ranges) is None and units.volume_of(1, None) is None
