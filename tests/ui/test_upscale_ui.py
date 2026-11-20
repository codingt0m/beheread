"""Tests d'interface de l'upscaling (ui/reader/upscale.py, preferences) :
bouton du HUD present seulement si l'option est activee, animation de
chargement tant qu'une page affichee attend sa version amelioree, pages
ameliorees affichees, bascule par serie. Le service est remplace par un
faux, pilote par le test (aucun moteur, aucun GPU)."""

import pytest
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent
from PySide6.QtWidgets import QApplication

from beheread.infra import upscaler
from beheread.services import upscaling
from beheread.ui import theme
from tests.ui.conftest import make_cbz


class FakeService(QObject):
    ready = Signal(int, QImage)
    skipped = Signal(int)
    unavailable = Signal(str)
    instances = []

    def __init__(self, archive, volume_key, cache=None, parent=None):
        super().__init__(parent)
        self.wants = []
        self.stopped = False
        FakeService.instances.append(self)

    def want(self, current, have, screen, fit_width):
        self.wants.append(list(current))

    def stop(self):
        self.stopped = True


@pytest.fixture
def fake_service(monkeypatch):
    FakeService.instances = []
    monkeypatch.setattr(upscaling, "UpscaleService", FakeService)
    return FakeService


def _open(window, qtbot, path):
    window.open_manga(path)
    reader = window.reader
    qtbot.waitUntil(lambda: 0 in reader.cache and not reader.cache[0].isNull(), timeout=10000)
    return reader


def _key(reader, key):
    QApplication.sendEvent(reader, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))


def _sharp(reader, index):
    src = reader.cache[index]
    img = QImage(src.width() * 2, src.height() * 2, QImage.Format_RGB32)
    img.fill(QColor("#123456"))
    return img


def test_no_button_and_no_work_while_the_option_is_off(window, qtbot, mangas, store,
                                                        fake_service):
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1"))
    assert reader.chip_upscale.isHidden() and not fake_service.instances
    _key(reader, Qt.Key_U)
    assert not fake_service.instances and not reader._upscale_waiting()


def test_page_waits_with_an_animation_then_shows_its_sharp_version(window, qtbot, mangas, store,
                                                                    fake_service):
    store.set_reader_pref("upscale_enabled", True)
    store.set_reader_pref("double_page", False)
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1", size=(300, 420)))
    chip = reader.chip_upscale
    assert not chip.isHidden() and chip.isChecked() and chip.isEnabled()
    service = fake_service.instances[-1]
    assert service.wants and service.wants[-1] == [reader.page]

    # page affichee pas encore prete : anneau dans le bouton, texte sous le numero
    qtbot.waitUntil(reader._upscale_waiting, timeout=5000)
    reader._refresh_upscale_indicator()
    assert reader._upscale_timer.isActive()
    qtbot.waitUntil(lambda: not chip.icon().isNull(), timeout=2000)
    assert "Amélioration de la page…" in reader.hud_sub.text()

    # HUD masque : la pastille prend le relais
    reader._hide_chrome()
    assert reader._upscale_badge.isVisible()
    reader._show_chrome()
    assert not reader._upscale_badge.isVisible()

    # version nette arrivee : affichee a la place de l'originale, plus d'animation
    sharp = _sharp(reader, reader.page)
    service.ready.emit(reader.page, sharp)
    assert reader._upscaled[reader.page] is not None
    assert reader._display_source(reader.page, None)[0].size() == sharp.size()
    assert not reader._upscale_waiting() and not reader._upscale_timer.isActive()
    assert chip.icon().isNull() and "Amélioration" not in reader.hud_sub.text()
    reader.repaint()


def test_upscaled_crop_follows_the_sharp_image_scale(window, qtbot, mangas, store, fake_service):
    from PySide6.QtCore import QRect
    store.set_reader_pref("upscale_enabled", True)
    store.set_reader_pref("double_page", False)
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1", size=(300, 420)))
    fake_service.instances[-1].ready.emit(0, _sharp(reader, 0))
    img, crop = reader._display_source(0, QRect(10, 20, 100, 200))
    assert img.width() == 600 and crop == QRect(20, 40, 200, 400)


def test_button_and_key_turn_it_off_for_the_series(window, qtbot, mangas, store, fake_service):
    store.set_reader_pref("upscale_enabled", True)
    first = make_cbz(mangas, "Alpha - Tome 1")
    reader = _open(window, qtbot, first)
    service = fake_service.instances[-1]
    _key(reader, Qt.Key_U)
    assert not reader.upscale_on and not reader.chip_upscale.isChecked() and service.stopped
    assert not reader._upscale_waiting() and not reader._upscale_timer.isActive()
    assert store.reader_setting("upscale", reader._series_key) is False
    reader.chip_upscale.click()
    assert reader.upscale_on and fake_service.instances[-1] is not service


def test_unavailable_engine_greys_out_the_button(window, qtbot, mangas, store, fake_service):
    store.set_reader_pref("upscale_enabled", True)
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1"))
    fake_service.instances[-1].unavailable.emit("gpu")
    chip = reader.chip_upscale
    assert not chip.isEnabled() and not chip.isChecked()
    assert chip.toolTip() == "Aucun GPU compatible (Vulkan)"
    assert not reader._upscale_waiting()
    _key(reader, Qt.Key_U)   # sans effet
    assert reader.upscale_on and reader._upscale_unavailable == "gpu"


def test_closing_the_reader_stops_the_service(window, qtbot, mangas, store, fake_service):
    store.set_reader_pref("upscale_enabled", True)
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1"))
    service = fake_service.instances[-1]
    reader.close_reader()
    assert service.stopped and not reader._upscaled


def test_preferences_option_off_by_default_shows_engine_and_cache_when_on(qtbot, store,
                                                                          monkeypatch):
    from beheread.ui.library.dialogs import PreferencesDialog
    monkeypatch.setattr(upscaler, "_probe_result",
                        upscaler.Probe(True, gpu="Qualcomm(R) Adreno(TM) X1-85 GPU"))
    dlg = PreferencesDialog(store, theme.colors("dark"), {})
    qtbot.addWidget(dlg)
    assert not dlg.upscale.isChecked()
    assert dlg._upscale_engine_row.isHidden() and dlg._upscale_cache_row.isHidden()
    dlg.upscale.setChecked(True)
    assert store.reader_pref("upscale_enabled") is True
    assert not dlg._upscale_engine_row.isHidden() and not dlg._upscale_cache_row.isHidden()
    assert dlg._upscale_status.text() == "Prêt"
    assert "Adreno" in dlg._upscale_engine_hint.text()
    assert "sur 2,0 Go" in dlg._upscale_cache_hint.text()
    dlg.upscale.setChecked(False)
    assert store.reader_pref("upscale_enabled") is False


def test_resuming_mid_volume_never_asks_for_the_beginning(window, qtbot, mangas, store,
                                                          fake_service):
    from beheread.services.upscaling import hold_window
    store.set_reader_pref("upscale_enabled", True)
    store.set_reader_pref("double_page", False)
    path = make_cbz(mangas, "Alpha - Tome 1", pages=40)
    store.set_progress(path, 25, 40, False)
    window.open_manga(path)
    reader = window.reader
    assert reader.page == 25
    service = fake_service.instances[-1]
    # des la premiere demande : la page reprise, jamais la page 1
    assert service.wants and all(w == [25] for w in service.wants)
    # le service ne prepare que la fenetre autour d'elle
    assert min(hold_window([25], 40)) == 23


def test_double_page_turns_sharp_both_pages_at_once(window, qtbot, mangas, store, fake_service):
    store.set_reader_pref("upscale_enabled", True)
    store.set_reader_pref("double_page", True)
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1", pages=6, size=(300, 420)))
    reader._go_to(2, animate=False)
    left, right = reader._current_indices()
    qtbot.waitUntil(lambda: left in reader.cache and right in reader.cache, timeout=5000)
    service = fake_service.instances[-1]

    def shown_sharp():
        return [reader._display_source(i, None)[0] is not reader.cache[i] for i in (left, right)]

    # une seule page prete : les deux restent telles quelles, l'attente continue
    service.ready.emit(left, _sharp(reader, left))
    assert shown_sharp() == [False, False] and reader._upscale_waiting()
    # la seconde arrive : les deux passent nettes ensemble
    service.ready.emit(right, _sharp(reader, right))
    assert shown_sharp() == [True, True] and not reader._upscale_waiting()
    reader.repaint()

    # page suivante : l'une echoue dans le moteur, toute la vue reste d'origine
    reader._go_to(4, animate=False)
    a, b = reader._current_indices()
    qtbot.waitUntil(lambda: a in reader.cache and b in reader.cache, timeout=5000)
    service.ready.emit(a, _sharp(reader, a))
    service.skipped.emit(b)
    assert [reader._display_source(i, None)[0] is reader.cache[i] for i in (a, b)] == [True, True]
    assert not reader._upscale_waiting() and not reader._upscale_timer.isActive()
