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
    # outils retenus : restaures apres le test (sinon le faux UnRAR.exe sert
    # aux tests suivants, ex. l'extraction des RAR solides)
    monkeypatch.setattr(archive, "_rar_tools", {})
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


def test_solid_rar_is_extracted_once_for_reading(monkeypatch):
    """RAR solide ouvert dans le lecteur : toutes les pages sont extraites en
    une passe, puis lues depuis le disque ; le dossier part a la fermeture."""
    import time as _time

    ar = _open_rar_or_skip(RAR5)
    try:
        expected = [ar.read_page(i) for i in range(len(ar))]
        monkeypatch.setattr(ar._ar, "is_solid", lambda: True)
        ar.prepare_reading()
        deadline = _time.monotonic() + 20
        while not (ar._solid_ready or ar._solid_failed) and _time.monotonic() < deadline:
            _time.sleep(0.02)
        assert ar._solid_ready
        monkeypatch.setattr(ar._ar, "read", lambda name: pytest.fail("lu dans l'archive"))
        assert [ar.read_page(i) for i in range(len(ar))] == expected
        folder = ar._solid_dir
    finally:
        ar.close()
    assert not folder.exists()


def test_non_solid_archives_are_not_extracted(tmp_path):
    ar = Archive(_make_cbz(tmp_path / "a.cbz"))
    try:
        ar.prepare_reading()
        assert ar._solid_dir is None
    finally:
        ar.close()


def _make_fixed_layout_epub(path, spine_images):
    """EPUB a mise en page fixe : une page XHTML par image, dans l'ordre du
    spine ; les noms d'images ne disent rien de cet ordre."""
    items, refs = [], []
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml",
                    '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:'
                    'xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/>'
                    '</rootfiles></container>')
        for i, image in enumerate(spine_images):
            zf.writestr(f"OEBPS/images/{image}", f"image-{image}".encode())
            zf.writestr(f"OEBPS/text/p{i}.xhtml",
                        f'<html><body>&nbsp;<svg><image xlink:href="../images/{image}"/></svg>'
                        f"</body></html>")
            items.append(f'<item id="p{i}" href="text/p{i}.xhtml" '
                         f'media-type="application/xhtml+xml"/>')
            refs.append(f'<itemref idref="p{i}"/>')
        zf.writestr("OEBPS/images/hors-spine.jpg", b"orpheline")
        zf.writestr("OEBPS/content.opf",
                    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf">'
                    f'<manifest>{"".join(items)}</manifest><spine>{"".join(refs)}</spine>'
                    '</package>')
    return str(path)


def test_epub_pages_follow_the_spine(tmp_path):
    order = ["f3a9.jpg", "07b1.jpg", "c2d4.jpg"]       # noms sans ordre
    ar = Archive(_make_fixed_layout_epub(tmp_path / "livre.epub", order))
    try:
        assert ar.pages == [f"OEBPS/images/{n}" for n in order] + ["OEBPS/images/hors-spine.jpg"]
        assert ar.read_page(0) == b"image-f3a9.jpg"
    finally:
        ar.close()


@pytest.mark.parametrize("names, expected", [
    (["001.jpg", "002.jpg", "zzz-credits.jpg"], ["001.jpg", "002.jpg"]),
    (["001.jpg", "credits_team.png", "002.jpg", "zz_recrutement.jpg"], ["001.jpg", "002.jpg"]),
    (["001.jpg", "Accredited.jpg"], ["001.jpg", "Accredited.jpg"]),   # mot entier seulement
    (["credits.jpg"], ["credits.jpg"]),                               # jamais un tome vide
])
def test_scanlation_extra_images_are_not_pages(tmp_path, names, expected):
    path = tmp_path / "t.cbz"
    with zipfile.ZipFile(path, "w") as zf:
        for n in names:
            zf.writestr(n, b"img")
    ar = Archive(str(path))
    try:
        assert ar.pages == expected
    finally:
        ar.close()


def test_extra_page_words_follow_the_preferences(tmp_path):
    path = tmp_path / "t.cbz"
    with zipfile.ZipFile(path, "w") as zf:
        for n in ("001.jpg", "002.jpg", "teamscan-pub.jpg", "zzz-credits.jpg"):
            zf.writestr(n, b"img")
    try:
        archive.set_extra_page_words(["teamscan"])        # « zz » retire, « teamscan » ajoute
        ar = Archive(str(path))
        assert ar.pages == ["001.jpg", "002.jpg", "zzz-credits.jpg"]
        ar.close()
    finally:
        archive.set_extra_page_words(None)
    ar = Archive(str(path))
    assert ar.pages == ["001.jpg", "002.jpg", "teamscan-pub.jpg"]
    ar.close()


def test_comicinfo_extras_are_parsed(tmp_path):
    """Nombre de tomes, genres, resume, langue et ISBN (comme Komga)."""
    xml = ("<?xml version='1.0'?><ComicInfo><Series>Saga</Series><Count>12</Count>"
           "<Genre>Science-fiction, Fantasy</Genre><Summary>Alana et Marko</Summary>"
           "<LanguageISO>fr</LanguageISO><GTIN>978-2-36577-250-1</GTIN></ComicInfo>")
    ar = Archive(_make_cbz(tmp_path / "saga.cbz", comicinfo=xml.encode()))
    try:
        meta = ar.read_comicinfo()
    finally:
        ar.close()
    assert meta["count"] == 12 and meta["genres"] == ["Science-fiction", "Fantasy"]
    assert meta["summary"] == "Alana et Marko" and meta["language"] == "fr"
    assert meta["gtin"] == "9782365772501" and meta["embedded"] == "comicinfo"


def _make_tagged_epub(path, metadata, spine='<spine page-progression-direction="rtl"/>'):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml",
                    '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:'
                    'xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/>'
                    '</rootfiles></container>')
        zf.writestr("OEBPS/images/001.jpg", b"img")
        zf.writestr("OEBPS/content.opf",
                    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
                    'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                    f"<metadata>{metadata}</metadata><manifest/>{spine}</package>")
    return str(path)


def test_epub_opf_metadata(tmp_path):
    """EPUB sans ComicInfo.xml : serie (EPUB 3), auteur, date, sens de
    lecture du spine, sujets, ISBN."""
    ar = Archive(_make_tagged_epub(tmp_path / "op.epub", (
        "<dc:title>One Piece 12</dc:title><dc:creator>Eiichirō Oda</dc:creator>"
        "<dc:date>2001-05-02</dc:date><dc:subject>Aventure; Pirates</dc:subject>"
        "<dc:identifier>urn:isbn:9782723434621</dc:identifier><dc:publisher>Glénat</dc:publisher>"
        '<meta property="belongs-to-collection" id="c1">One Piece</meta>'
        '<meta refines="#c1" property="group-position">12</meta>')))
    try:
        meta = ar.read_comicinfo()
    finally:
        ar.close()
    assert meta["series"] == "One Piece" and meta["number"] == 12
    assert meta["authors"] == ["Eiichirō Oda"] and meta["year"] == 2001
    assert meta["reading_direction"] == "rtl" and meta["genres"] == ["Aventure", "Pirates"]
    assert meta["gtin"] == "9782723434621" and meta["embedded"] == "opf"


def test_epub_calibre_series(tmp_path):
    ar = Archive(_make_tagged_epub(tmp_path / "c.epub", (
        '<dc:title>Tome 3</dc:title><meta name="calibre:series" content="Blacksad"/>'
        '<meta name="calibre:series_index" content="3.0"/>'), spine="<spine/>"))
    try:
        meta = ar.read_comicinfo()
    finally:
        ar.close()
    assert meta["series"] == "Blacksad" and meta["number"] == 3
    assert meta["reading_direction"] is None


def test_isbn_is_read_from_the_back_cover(tmp_path, qapp):
    """Code-barres de la quatrieme de couverture (derniere page), dans une
    page JPEG ; une page sans code-barres n'en donne pas."""
    import itertools

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter

    from beheread.core import barcode

    def page(code=None):
        img = QImage(900, 1300, QImage.Format_RGB32)
        img.fill(QColor(220, 190, 140))
        if code:
            p = QPainter(img)
            p.fillRect(560, 1050, 330, 200, Qt.white)
            x = 0
            for dark, run in itertools.groupby(barcode.encode(code)):
                n = len(list(run))
                if dark:
                    p.fillRect(QRectF(580 + x * 3, 1070, n * 3, 150), Qt.black)
                x += n
            p.end()
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "JPEG", 80)
        return bytes(data)

    path = tmp_path / "vf.cbz"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("001.jpg", page())
        zf.writestr("002.jpg", page())
        zf.writestr("003.jpg", page("9782505063520"))
    ar = Archive(str(path))
    try:
        assert ar.find_isbn() == "9782505063520"
    finally:
        ar.close()
    blank = tmp_path / "blank.cbz"
    with zipfile.ZipFile(blank, "w") as zf:
        zf.writestr("001.jpg", page())
    ar = Archive(str(blank))
    try:
        assert ar.find_isbn() is None
    finally:
        ar.close()
