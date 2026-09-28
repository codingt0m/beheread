"""Tests du support PDF (infra/archive.PdfArchive) : les pages d'un PDF sont
rendues a la demande et exposees comme celles d'une archive d'images."""

import pytest

from beheread.infra.archive import (SUPPORTED_EXTS, Archive, ArchiveClosedError,
                             ArchiveError, PdfArchive)


def _make_pdf(path, colors=("red", "green", "blue")):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QPageSize, QPainter, QPdfWriter
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A5))
    writer.setResolution(72)
    painter = QPainter(writer)
    for i, color in enumerate(colors):
        if i:
            writer.newPage()
        painter.fillRect(QRectF(20, 20, 100, 100), QColor(color))
    painter.end()
    return str(path)


def test_pdf_is_a_supported_extension():
    assert ".pdf" in SUPPORTED_EXTS


def test_archive_dispatches_to_pdf(qapp, tmp_path):
    ar = Archive(_make_pdf(tmp_path / "a.pdf"))
    try:
        assert isinstance(ar, PdfArchive)
        assert len(ar) == 3
        assert ar.read_comicinfo() is None
    finally:
        ar.close()


def test_pdf_page_rendered_on_white(qapp, tmp_path):
    """PDFium rend un fond transparent : la page doit etre composee sur du
    blanc (sinon le texte apparaitrait sur le fond noir du lecteur)."""
    from PySide6.QtGui import QColor
    ar = Archive(_make_pdf(tmp_path / "a.pdf"))
    try:
        img = ar.read_image(1)
        assert not img.isNull()
        assert max(img.width(), img.height()) >= 1400      # net en plein ecran
        corner = QColor(img.pixel(img.width() - 5, img.height() - 5))
        assert (corner.red(), corner.green(), corner.blue()) == (255, 255, 255)
        square = QColor(img.pixel(img.width() // 10, img.height() // 12))
        assert square.green() > 100 and square.red() < 50  # page 2 : carre vert
    finally:
        ar.close()


def test_pdf_thumbnail_height_is_bounded(qapp, tmp_path):
    ar = Archive(_make_pdf(tmp_path / "a.pdf"))
    try:
        assert ar.read_image(0, max_height=300).height() <= 300
    finally:
        ar.close()


def test_invalid_pdf_raises_archive_error(qapp, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 ceci n'est pas un vrai pdf")
    with pytest.raises(ArchiveError):
        Archive(str(bad))


def test_pdf_read_after_close(qapp, tmp_path):
    ar = Archive(_make_pdf(tmp_path / "a.pdf"))
    ar.close()
    ar.close()   # idempotent
    with pytest.raises(ArchiveClosedError):
        ar.read_image(0)
