"""Tests du moteur d'upscaling (infra/upscaler.py) et de son service
(services/upscaling.py), avec un faux moteur : un script Python qui agrandit
x2 comme le vrai, sans GPU."""

import sys
import time

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage

from beheread.infra import upscaler
from beheread.infra.archive import Archive
from tests.ui.conftest import make_cbz

FAKE_ENGINE = r'''
import sys
from pathlib import Path
from PySide6.QtGui import QImage
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
src, dst = Path(args["-i"]), Path(args["-o"])
# GPU qui manque de memoire pour des tuiles imposees (voir le test du repli)
if "-t" in args and (Path(__file__).parent / "fail_with_tiles").exists():
    sys.exit(1)
files = sorted(src.iterdir()) if src.is_dir() else [src]
for f in files:
    img = QImage(str(f))
    out = img.scaled(img.width() * int(args["-s"]), img.height() * int(args["-s"]))
    target = dst / (f.stem + ".png") if dst.is_dir() else dst
    out.save(str(target))
print("[0 Fausse carte graphique]  queueC=0[1]", file=sys.stderr)
'''


@pytest.fixture
def fake_engine(tmp_path, monkeypatch):
    script = tmp_path / "fake_engine.py"
    script.write_text(FAKE_ENGINE, encoding="utf-8")
    real_command = upscaler.command
    monkeypatch.setattr(upscaler, "engine_path", lambda: script)
    monkeypatch.setattr(upscaler, "command",
                        lambda exe, src, dst, tile=upscaler.TILE: [sys.executable, str(exe)]
                        + real_command("x", src, dst, tile)[1:])
    monkeypatch.setattr(upscaler, "_probe_result", None)
    return script


def _png(img):
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def test_gpu_name_and_formats_read_by_the_engine():
    err = ("[0 Qualcomm(R) Adreno(TM) X1-85 GPU]  queueC=0[4]\n"
           "[1 Microsoft Direct3D12 (Qualcomm(R) Adreno(TM) X1-85 GPU)]  queueC=1[8]\n")
    assert upscaler.parse_gpu(err) == "Qualcomm(R) Adreno(TM) X1-85 GPU"
    assert upscaler.parse_gpu("vkCreateInstance failed") == ""
    assert upscaler.image_ext(b"\xff\xd8\xff\xe0....") == "jpg"
    assert upscaler.image_ext(b"\x89PNG\r\n\x1a\n....") == "png"
    assert upscaler.image_ext(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert upscaler.image_ext(b"GIF89a") is None


def test_missing_engine_is_reported_as_such(monkeypatch):
    monkeypatch.setattr(upscaler, "engine_path", lambda: None)
    assert upscaler.probe() == upscaler.Probe(False, reason="engine")


def test_probe_with_a_working_engine(qapp, fake_engine):
    assert upscaler.probe() == upscaler.Probe(True, gpu="Fausse carte graphique")


def test_batch_returns_each_page_once_complete(qapp, fake_engine):
    jobs = []
    for index in (7, 3):
        img = QImage(40, 60, QImage.Format_RGB32)
        img.fill(QColor("#336699"))
        jobs.append((index, _png(img), "png"))
    batch = upscaler.Batch(jobs).start(fake_engine)
    done = {}
    deadline = time.monotonic() + 30
    try:
        while (batch.pending or not batch.finished) and time.monotonic() < deadline:
            for index, path in batch.poll():
                done[index] = QImage(str(path)).size().toTuple()
            time.sleep(0.05)
    finally:
        batch.cleanup()
    assert done == {7: (80, 120), 3: (80, 120)} and batch.returncode == 0


def test_disk_cache_keeps_gray_as_png_color_as_jpeg_and_stays_bounded(qapp, tmp_path):
    cache = upscaler.DiskCache(tmp_path / "up", limit=10 ** 9)
    gray = QImage(100, 140, QImage.Format_Grayscale8)
    gray.fill(128)
    color = QImage(100, 140, QImage.Format_RGB32)
    color.fill(QColor("#aa3355"))
    cache.save("tome A", 0, gray)
    cache.save("tome A", 1, color)
    assert cache.load("tome A", 0).format() == QImage.Format_Grayscale8
    assert cache.load("tome A", 1).size().toTuple() == (100, 140)
    assert cache.load("tome A", 2) is None and cache.load("tome B", 0) is None
    files = sorted(p.suffix for p in (tmp_path / "up").rglob("*.*"))
    assert files == [".jpg", ".png"]
    # plafond : les moins recemment lues partent d'abord
    cache.limit = cache.size() - 1
    cache.load("tome A", 0)          # lue a l'instant : gardee
    time.sleep(0.05)
    cache.trim()
    assert cache.load("tome A", 0) is not None and cache.load("tome A", 1) is None
    assert cache.clear() > 0 and cache.size() == 0


def test_service_prepares_shown_then_next_pages_at_display_size(qapp, qtbot, tmp_path,
                                                                 fake_engine):
    from beheread.services.upscaling import UpscaleService
    path = make_cbz(tmp_path, "Alpha - Tome 1", pages=5, size=(300, 420))
    archive = Archive(path)
    cache = upscaler.DiskCache(tmp_path / "cache")
    service = UpscaleService(archive, "cle-alpha", cache=cache)
    ready = {}
    service.ready.connect(lambda i, img: ready.__setitem__(i, img))
    try:
        # ecran de 600 x 840 : pages de 300 x 420 agrandies x2
        service.want([2], set(), (600, 840), False)
        qtbot.waitUntil(lambda: len(ready) == 5, timeout=30000)
        assert {i: img.size().toTuple() for i, img in ready.items()} == {
            i: (600, 840) for i in range(5)}
        # gardees sur le disque (apres l'affichage) : un autre lecteur les
        # reprend sans le moteur
        qtbot.waitUntil(lambda: all(cache.load("cle-alpha", i) is not None for i in range(5)),
                        timeout=10000)
    finally:
        service.stop()
        service.join(10)
        archive.close()


def test_service_skips_pages_large_enough_and_reports_a_missing_engine(qapp, qtbot, tmp_path,
                                                                       monkeypatch, fake_engine):
    from beheread.services.upscaling import UpscaleService
    path = make_cbz(tmp_path, "Beta - Tome 1", pages=2, size=(300, 420))
    archive = Archive(path)
    service = UpscaleService(archive, "cle-beta", cache=upscaler.DiskCache(tmp_path / "c"))
    skipped = []
    service.skipped.connect(skipped.append)
    try:
        service.want([0], set(), (300, 420), False)   # ecran a la taille des pages
        qtbot.waitUntil(lambda: sorted(skipped) == [0, 1], timeout=30000)
    finally:
        service.stop()
        service.join(10)

    monkeypatch.setattr(upscaler, "_probe_result", upscaler.Probe(False, reason="gpu"))
    service = UpscaleService(archive, "cle-beta", cache=upscaler.DiskCache(tmp_path / "c"))
    reasons = []
    service.unavailable.connect(reasons.append)
    try:
        service.want([0], set(), (600, 840), False)
        qtbot.waitUntil(lambda: reasons == ["gpu"], timeout=10000)
    finally:
        service.stop()
        service.join(10)
        archive.close()


def test_batch_queue_position_of_a_page():
    batch = upscaler.Batch([(5, b"", "png"), (6, b"", "png"), (7, b"", "png")])
    assert [batch.queued_before(i) for i in (5, 6, 7)] == [0, 1, 2]
    batch.pending.discard(5)
    assert batch.queued_before(7) == 1


def test_restart_when_the_shown_page_waits_behind_others():
    from beheread.services.upscaling import UpscaleService
    batch = upscaler.Batch([(i, b"", "png") for i in range(10, 16)])
    restart = UpscaleService._should_restart
    assert not restart(batch, [10], set())            # en tete du lot
    assert not restart(batch, [11], set())            # une page devant : on attend
    assert restart(batch, [12], set())                # lecture plus rapide que le moteur
    assert restart(batch, [150], set())               # saut hors du lot
    assert not restart(batch, [150], {150})           # deja prete
    assert not restart(batch, [10, 11], set())        # double page : la premiere est en tete


def test_service_falls_back_to_automatic_tiles_when_the_gpu_refuses(qapp, qtbot, tmp_path,
                                                                    fake_engine):
    from beheread.services.upscaling import UpscaleService
    (fake_engine.parent / "fail_with_tiles").write_text("")
    path = make_cbz(tmp_path, "Gamma - Tome 1", pages=2, size=(300, 420))
    archive = Archive(path)
    service = UpscaleService(archive, "cle-gamma", cache=upscaler.DiskCache(tmp_path / "c"))
    ready, reasons = {}, []
    service.ready.connect(lambda i, img: ready.__setitem__(i, img))
    service.unavailable.connect(reasons.append)
    try:
        service.want([0], set(), (600, 840), False)
        qtbot.waitUntil(lambda: len(ready) == 2, timeout=30000)
        assert not reasons and service._tile == 0
    finally:
        service.stop()
        service.join(10)
        archive.close()


def test_service_without_any_working_gpu_becomes_unavailable(qapp, qtbot, tmp_path,
                                                             monkeypatch, fake_engine):
    from beheread.services.upscaling import UpscaleService
    fake_engine.write_text("import sys; sys.exit(3)", encoding="utf-8")
    path = make_cbz(tmp_path, "Delta - Tome 1", pages=2, size=(300, 420))
    archive = Archive(path)
    service = UpscaleService(archive, "cle-delta", cache=upscaler.DiskCache(tmp_path / "c"))
    reasons = []
    service.unavailable.connect(reasons.append)
    try:
        service.want([0], set(), (600, 840), False)
        qtbot.waitUntil(lambda: reasons == ["gpu"], timeout=30000)
        assert upscaler.known_probe() == upscaler.Probe(False, reason="gpu")
    finally:
        service.stop()
        service.join(10)
        archive.close()
