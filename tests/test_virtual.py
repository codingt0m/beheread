"""Tomes virtuels : chapitres lus a la suite comme un seul tome
(infra/virtual.py)."""

import zipfile

import pytest

from beheread.core.series import parse_path
from beheread.infra import virtual
from beheread.infra.archive import Archive, ArchiveError, find_next_volume


def _cbz(folder, name, pages):
    path = folder / f"{name}.cbz"
    with zipfile.ZipFile(path, "w") as z:
        for k in range(pages):
            z.writestr(f"{k:03}.jpg", f"{name}-{k}".encode())
    return str(path)


def test_virtual_path_reads_like_a_volume_of_its_series():
    path = virtual.make_path("abc", "Dr. Stone", 23)
    assert virtual.is_virtual(path) and virtual.volume_id(path) == "abc"
    name, number, kind = parse_path(path)
    assert (name, number, kind) == ("Dr. Stone", 23, "volume")
    assert find_next_volume(path) is None


def test_virtual_archive_chains_the_pages_of_its_chapters(tmp_path):
    a = _cbz(tmp_path, "Serie Chapitre 1", 2)
    b = _cbz(tmp_path, "Serie Chapitre 2", 3)
    path = virtual.make_path("v1", "Serie", 1)
    virtual.registry.set_all({path: [a, b]})
    try:
        ar = Archive(path)
        assert isinstance(ar, virtual.VirtualArchive) and len(ar) == 5
        assert ar.read_page(0) == b"Serie Chapitre 1-0"
        assert ar.read_page(2) == b"Serie Chapitre 2-0"
        assert ar.read_page(4) == b"Serie Chapitre 2-2"
        assert ar.spans == [(0, 1, a), (2, 4, b)]
        assert ar.chapter_at(3) == b and ar.read_comicinfo() is None
        ar.close()
    finally:
        virtual.registry.set_all({})


def test_virtual_archive_without_chapters_is_an_archive_error():
    with pytest.raises(ArchiveError):
        Archive(virtual.make_path("gone", "Serie", 1))


def test_chapters_read_in_a_virtual_volume():
    spans = [(0, 9, "c1"), (10, 19, "c2"), (20, 29, "c3")]
    assert virtual.chapters_read(spans, 15, False) == ["c1"]
    assert virtual.chapters_read(spans, 20, False) == ["c1", "c2"]
    assert virtual.chapters_read(spans, 0, True) == ["c1", "c2", "c3"]
