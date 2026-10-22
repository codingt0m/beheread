"""Deplacement de fichiers d'un dossier source a un autre (infra/relocate.py)."""

from beheread.infra import relocate


def test_destination_keeps_the_subfolder(tmp_path):
    local, cloud = tmp_path / "Mangas", tmp_path / "iCloud" / "Mangas"
    sources = [str(local), str(cloud), str(local / "Chainsaw Man")]
    path = local / "Chainsaw Man" / "T01.cbz"
    # dossier source le plus profond : « Chainsaw Man » est lui-meme une source
    assert relocate.source_root(path, sources) == str(local / "Chainsaw Man")
    assert relocate.destination(local / "Berserk" / "T01.cbz", sources, cloud) == \
        cloud / "Berserk" / "T01.cbz"
    assert relocate.destination(tmp_path / "ailleurs.cbz", sources, cloud) == cloud / "ailleurs.cbz"


def test_plan_skips_files_already_there(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    pairs = relocate.plan([str(a / "x.cbz"), str(b / "y.cbz"), str(a / "x.cbz")],
                          [str(a), str(b)], str(b))
    assert pairs == [(str(a / "x.cbz"), str(b / "x.cbz"))]


def test_move_creates_folders_and_never_overwrites(tmp_path):
    src = tmp_path / "A" / "Serie" / "T01.cbz"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"tome")
    dst = tmp_path / "B" / "Serie" / "T01.cbz"
    assert relocate.move(src, dst) == relocate.MOVED
    assert dst.read_bytes() == b"tome" and not src.exists()

    other = tmp_path / "A" / "Serie" / "T01.cbz"
    other.write_bytes(b"autre")
    assert relocate.move(other, dst) == relocate.EXISTS
    assert dst.read_bytes() == b"tome" and other.exists()
