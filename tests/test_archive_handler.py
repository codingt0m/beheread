import zipfile

import archive_handler


def _make_epub(path, image_names):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        for name in image_names:
            zf.writestr(f"OEBPS/images/{name}", b"fake-image-bytes")
    return path


def test_epub_extension_is_supported():
    assert ".epub" in archive_handler.SUPPORTED_EXTS


def test_scan_folder_finds_epub(tmp_path):
    epub_path = tmp_path / "volume01.epub"
    _make_epub(epub_path, ["page001.jpg", "page002.jpg"])

    results = archive_handler.scan_folder(str(tmp_path))

    assert str(epub_path) in results


def test_archive_reads_pages_from_epub(tmp_path):
    epub_path = tmp_path / "volume01.epub"
    _make_epub(epub_path, ["page002.jpg", "page001.jpg"])

    ar = archive_handler.Archive(str(epub_path))
    try:
        assert len(ar) == 2
        assert ar.pages[0].endswith("page001.jpg")
        assert ar.pages[1].endswith("page002.jpg")
        assert ar.read_first_page() == b"fake-image-bytes"
    finally:
        ar.close()
