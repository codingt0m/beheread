import sys
import zipfile
from pathlib import Path

import pytest

from beheread.infra import archive
from beheread.infra.archive import Archive, ArchiveError


def _make_epub(path, image_names):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        for name in image_names:
            zf.writestr(f"OEBPS/images/{name}", b"fake-image-bytes")
    return path


def _make_cbz(path, comicinfo=None, image_bytes=b"\xff\xd8\xff\xe0img"):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("001.jpg", image_bytes)
        if comicinfo is not None:
            zf.writestr("ComicInfo.xml", comicinfo)
    return str(path)


def test_read_page_rejects_decompression_bomb(tmp_path, monkeypatch):
    """Une page dont la taille decompressee annoncee depasse le plafond est
    refusee sans etre lue (garde-fou anti bombe de decompression)."""
    path = _make_cbz(tmp_path / "big.cbz", image_bytes=b"x" * 50)
    monkeypatch.setattr(archive, "MAX_PAGE_BYTES", 10)
    ar = Archive(path)
    try:
        with pytest.raises(ArchiveError):
            ar.read_first_page()
    finally:
        ar.close()


def test_comicinfo_with_doctype_is_ignored(tmp_path):
    """Un ComicInfo.xml contenant un DOCTYPE (vecteur d'expansion d'entites /
    XXE) est ignore par securite : la cascade se rabat sur le reseau."""
    bomb = (b'<?xml version="1.0"?>\n<!DOCTYPE r [ <!ENTITY a "x"> ]>\n'
            b'<ComicInfo><Series>&a;</Series></ComicInfo>')
    ar = Archive(_make_cbz(tmp_path / "d.cbz", comicinfo=bomb))
    try:
        assert ar.read_comicinfo() is None
    finally:
        ar.close()


def test_comicinfo_with_doctype_in_utf16_is_ignored(tmp_path):
    """Meme refus pour un ComicInfo.xml encode en UTF-16 (la sequence
    « <!DOCTYPE » n'y apparait pas telle quelle dans les octets)."""
    bomb = ('<?xml version="1.0" encoding="UTF-16"?>\n<!DOCTYPE r [ <!ENTITY a "x"> ]>\n'
            '<ComicInfo><Series>&a;</Series></ComicInfo>').encode("utf-16")
    ar = Archive(_make_cbz(tmp_path / "d16.cbz", comicinfo=bomb))
    try:
        assert ar.read_comicinfo() is None
    finally:
        ar.close()


def test_rarfile_only_runs_tools_found_by_absolute_path(tmp_path, monkeypatch):
    """rarfile ne doit jamais lancer un outil par son simple nom ("unrar",
    "7z"...) : sous Windows, il serait cherche dans le dossier courant, ou un
    unrar.exe piege peut accompagner un CBR telecharge."""
    import errno

    import rarfile

    launched = []

    def fake_popen(cmd, *args, **kwargs):
        launched.append(cmd[0])
        raise FileNotFoundError(errno.ENOENT, "absent", cmd[0])

    tool = tmp_path / "UnRAR.exe"
    tool.write_bytes(b"")
    for attr in ("UNRAR_TOOL", "UNAR_TOOL", "SEVENZIP_TOOL", "SEVENZIP2_TOOL",
                 "BSDTAR_TOOL", "CURRENT_SETUP"):
        monkeypatch.setattr(rarfile, attr, getattr(rarfile, attr))
    monkeypatch.setattr(rarfile, "Popen", fake_popen)
    monkeypatch.setattr(archive, "_rarfile", None)
    monkeypatch.setattr(archive, "_rar_error", None)
    monkeypatch.setattr(archive.platforms, "rar_tools", lambda app_dir: {
        "unrar": [Path("unrar"), tool], "sevenzip": [Path("7z")], "bsdtar": []})

    archive._init_rarfile()

    assert launched == [str(tool)]
    assert archive._rarfile is None and "Aucun outil" in archive._rar_error


def test_comicinfo_plain_is_parsed(tmp_path):
    """Sans DOCTYPE, un ComicInfo.xml normal reste lu normalement."""
    xml = (b'<?xml version="1.0"?><ComicInfo>'
           b'<Series>Naruto</Series><Year>2000</Year></ComicInfo>')
    ar = Archive(_make_cbz(tmp_path / "ok.cbz", comicinfo=xml))
    try:
        meta = ar.read_comicinfo()
        assert meta["series"] == "Naruto" and meta["year"] == 2000
    finally:
        ar.close()


def test_epub_extension_is_supported():
    assert ".epub" in archive.SUPPORTED_EXTS


def test_scan_folder_finds_epub(tmp_path):
    epub_path = tmp_path / "volume01.epub"
    _make_epub(epub_path, ["page001.jpg", "page002.jpg"])

    results = archive.scan_folder(str(tmp_path))

    assert str(epub_path) in results


def test_archive_reads_pages_from_epub(tmp_path):
    epub_path = tmp_path / "volume01.epub"
    _make_epub(epub_path, ["page002.jpg", "page001.jpg"])

    ar = archive.Archive(str(epub_path))
    try:
        assert len(ar) == 2
        assert ar.pages[0].endswith("page001.jpg")
        assert ar.pages[1].endswith("page002.jpg")
        assert ar.read_first_page() == b"fake-image-bytes"
    finally:
        ar.close()


def test_read_after_close_raises_archive_closed(tmp_path):
    """Un prechargement encore en file quand le lecteur se ferme doit echouer
    proprement (ArchiveClosedError), sans lire un fichier ferme."""
    from beheread.infra.archive import ArchiveClosedError
    ar = Archive(_make_cbz(tmp_path / "a.cbz"))
    ar.close()
    ar.close()   # idempotent
    with pytest.raises(ArchiveClosedError):
        ar.read_first_page()


# --- vrais fichiers RAR -------------------------------------------------------
# tests/fixtures/rar5.cbr : 001.jpg, 002.jpg, 010.jpg (contenus "page-1"...)
# et info.txt, cree avec WinRAR 7 (format RAR5). Sous Windows, l'outil est
# UnRAR/7-Zip ; sous macOS, bsdtar suffit (fourni avec le systeme).

RAR5 = str(Path(__file__).parent / "fixtures" / "rar5.cbr")


def _open_rar_or_skip(path):
    try:
        return Archive(path)
    except ArchiveError as e:
        if "Aucun outil" in str(e):
            pytest.skip("aucun outil RAR sur cette machine")
        raise


def test_rar5_pages_are_listed_in_natural_order_and_read():
    ar = _open_rar_or_skip(RAR5)
    try:
        assert len(ar) == 3                       # info.txt n'est pas une page
        assert [ar.read_page(i) for i in range(3)] == [b"page-1", b"page-2", b"page-10"]
    finally:
        ar.close()


@pytest.mark.skipif(sys.platform != "darwin", reason="bsdtar : outil RAR de repli de macOS")
def test_rar5_opens_with_the_bsdtar_shipped_with_macos():
    archive._init_rarfile()
    rarfile = archive._rarfile
    rarfile.tool_setup(unrar=False, unar=False, sevenzip=False, sevenzip2=False,
                       bsdtar=True, force=True)
    try:
        ar = Archive(RAR5)
        try:
            assert [ar.read_page(i) for i in range(3)] == [b"page-1", b"page-2", b"page-10"]
        finally:
            ar.close()
    finally:
        _reset_rarfile()


def _reset_rarfile():
    """Refait la detection des outils RAR de Beheread (outils par chemin
    absolu seulement)."""
    archive._rarfile = archive._rar_error = None
    archive._init_rarfile()


def test_read_image_decodes_directly_at_the_requested_height(tmp_path, qapp):
    """Vignettes et apercus : l'image est decodee directement reduite."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage

    img = QImage(400, 800, QImage.Format_RGB32)
    img.fill(0x336699)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPEG")
    ar = Archive(_make_cbz(tmp_path / "big.cbz", image_bytes=bytes(data)))
    try:
        small = ar.read_image(0, max_height=200)
        full = ar.read_image(0)
    finally:
        ar.close()
    assert (small.width(), small.height()) == (100, 200)
    assert (full.width(), full.height()) == (400, 800)


def test_format_is_detected_once_per_opening(tmp_path, monkeypatch):
    path = _make_cbz(tmp_path / "a.cbz")
    calls = []
    real = archive._detect_format
    monkeypatch.setattr(archive, "_detect_format", lambda p: calls.append(p) or real(p))
    Archive(path).close()
    assert len(calls) == 1
