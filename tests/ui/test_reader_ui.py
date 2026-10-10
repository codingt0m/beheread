"""Tests d'interface du lecteur (pytest-qt)."""

import time

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QPushButton

from beheread.ui.reader.constants import FIT_HEIGHT, FIT_WIDTH
from tests.ui.conftest import make_cbz, make_pdf


def _open(window, qtbot, path):
    window.open_manga(path)
    reader = window.reader
    qtbot.waitUntil(lambda: 0 in reader.cache and not reader.cache[0].isNull(), timeout=10000)
    return reader


def _wheel(reader, dy, pixel=False):
    ev = QWheelEvent(QPointF(400, 300), QPointF(400, 300),
                     QPoint(0, dy) if pixel else QPoint(0, 0), QPoint(0, 0 if pixel else dy),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(reader, ev)
    reader.repaint()


def _session_record(store, path):
    days = store.reading_log.export()["devices"][store.device_id()]["days"]
    return next(iter(days.values()))[store.key_for(path)]


def _fake_clock(reader):
    """Remplace l'horloge de la seance : clock[0] est l'heure courante. La
    page affichee l'est « depuis maintenant » : le temps reel du chargement
    ne compte pas dans le test."""
    clock = [reader._now()]
    reader._now = lambda: clock[0]
    reader._meter._since = clock[0]
    return clock


def test_reading_saves_progress_and_session_stats(window, qtbot, mangas, store):
    store.set_reader_pref("double_page", False)
    path = make_cbz(mangas, "Alpha - Tome 1", pages=5)
    reader = _open(window, qtbot, path)
    clock = _fake_clock(reader)
    ended = []
    reader.session_ended.connect(ended.append)
    for _ in range(5):                 # 10 s par page, jusqu'a la fiche de fin
        clock[0] += 10
        reader.next_page(animate=False)
    assert store.get_progress(path)[2] is True
    assert reader._time_remaining_text() == ""          # derniere page : rien a estimer
    # la fin du tome est journalisee sans attendre la fermeture
    assert _session_record(store, path)["finished"] == 1
    clock[0] += 60                     # temps passe sur la fiche de fin : pas de la lecture
    reader.close_reader()
    assert ended == [path]
    record = _session_record(store, path)
    assert (record["pages"], record["seconds"], record["sessions"], record["finished"]) == (
        5, 50.0, 1, 1)
    assert store.median_page_seconds() == 10.0


def test_flipping_through_pages_is_not_reading(window, qtbot, mangas, store):
    path = make_cbz(mangas, "Alpha - Tome 1", pages=40)
    reader = _open(window, qtbot, path)
    clock = _fake_clock(reader)
    for value in range(1, 30):         # barre de defilement glissee, fleche maintenue
        clock[0] += 0.05
        reader._on_slider_scrub(value)
    reader.close_reader()
    days = store.reading_log.export()["devices"]
    assert days == {} and store.median_page_seconds() is None


def test_remaining_time_counts_pages_not_page_turns(window, qtbot, mangas, store):
    """En double page, un tour de page avance de deux pages : le rythme est
    en secondes par page, le temps restant n'est donc pas compte double."""
    path = make_cbz(mangas, "Alpha - Tome 1", pages=41)
    reader = _open(window, qtbot, path)
    assert reader.double_page
    clock = _fake_clock(reader)
    for _ in range(5):
        clock[0] += 30
        reader.next_page(animate=False)
    assert reader._meter.pace() == 15.0
    remaining = (reader.total - 1) - reader.page
    assert reader._time_remaining_text() == f"~{round(15 * remaining / 60)} min restantes"


def test_reader_always_opens_fullscreen(window, qtbot, mangas):
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1", seed=1))
    win = window.reader_window
    assert win.isFullScreen()
    assert reader.fullscreen_button.text().strip() == "Quitter le plein écran"
    # F11 ou le bouton du coin : fenetre maximisee, puis retour au plein ecran
    reader.fullscreen_button.click()
    qtbot.waitUntil(lambda: reader.fullscreen_button.text().strip() == "Plein écran")
    assert not win.isFullScreen() and win.isMaximized()
    win.toggle_fullscreen()
    assert win.isFullScreen()
    # tome suivant dans la meme fenetre : toujours en plein ecran, bouton a jour
    other = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 2", seed=2))
    assert window.reader_window is win and win.isFullScreen()
    assert other.fullscreen_button.text().strip() == "Quitter le plein écran"
    # nouvelle ouverture depuis la bibliotheque : de nouveau en plein ecran
    other.close_reader()
    assert window.reader_window is None
    _open(window, qtbot, make_cbz(mangas, "Beta - Tome 1", seed=3))
    assert window.reader_window.isFullScreen()


def test_wheel_scrolls_a_tall_page_before_turning(window, qtbot, mangas, store):
    store.set_reader_pref("fit_mode", 1)       # ajuster a la largeur
    store.set_reader_pref("double_page", False)
    path = make_cbz(mangas, "Webtoon - Tome 1", pages=3, size=(300, 900))
    window.resize(1200, 800)
    reader = _open(window, qtbot, path)
    window.reader_window.resize(1200, 800)
    reader.repaint()
    y0, h, vh = reader._view_geom
    assert h > vh and y0 == 0.0

    _wheel(reader, -120)
    assert reader.page == 0 and reader._view_geom[0] < 0     # a defile, pas tourne
    # rotation rapide et continue : la page defile jusqu'en bas sans tourner
    for _ in range(80):
        _wheel(reader, -120)
    y, h, vh = reader._view_geom
    assert reader.page == 0 and abs(y - (vh - h)) < 1
    # apres une pause, un cran de plus au bord tourne la page (affichee depuis son haut)
    time.sleep(0.25)
    _wheel(reader, -120)
    assert reader.page == 1
    reader.repaint()
    assert reader._view_geom[0] == 0.0


def test_touchpad_swipe_turns_a_single_page(window, qtbot, mangas, store):
    store.set_reader_pref("fit_mode", 2)       # ajuster a la hauteur
    store.set_reader_pref("double_page", False)
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1", pages=6))
    reader.repaint()
    for _ in range(60):
        _wheel(reader, -40, pixel=True)
    assert reader.page == 1


def test_reader_settings_follow_from_one_manga_to_another(window, qtbot, mangas, store):
    first = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1", seed=1))
    assert (first.double_page, first.manga_mode, first.smart_crop) == (True, True, False)
    assert first.fit_mode == FIT_HEIGHT and first.page_offset == 0
    first.toggle_double_page()
    first.toggle_manga_mode()
    first.toggle_smart_crop()
    first.cycle_fit_mode()
    first.toggle_double_page()      # de nouveau en double page, pour le decalage
    first._shift_parity()

    # une autre serie, jamais ouverte : memes reglages, decalage compris
    other = _open(window, qtbot, make_cbz(mangas, "Beta - Tome 1", seed=2))
    assert (other.double_page, other.smart_crop) == (True, True)
    assert other.fit_mode == FIT_WIDTH and other.page_offset == 1
    assert other.chip_crop.isChecked()

    # le dernier decalage choisi vaut partout, meme pour un tome deja regle
    other._shift_parity()
    assert _open(window, qtbot, first.path).page_offset == 0


def test_reading_direction_stays_per_series(window, qtbot, mangas, store):
    first = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1", seed=1))
    assert first.manga_mode is True
    first.toggle_manga_mode()
    # le choix vaut pour les tomes de la serie, pas pour une autre serie
    assert _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 2", seed=2)).manga_mode is False
    # M ne change pas le sens par defaut : une autre serie le garde
    assert store.reader_pref("manga_mode", True) is True
    assert _open(window, qtbot, make_cbz(mangas, "Beta - Tome 1", seed=3)).manga_mode is True
    store.set_reader_pref("manga_mode", False)    # sens par defaut des preferences
    assert _open(window, qtbot, make_cbz(mangas, "Delta - Tome 1", seed=5)).manga_mode is False
    store.set_reader_pref("manga_mode", True)
    # sans choix explicite : detection automatique (pays d'origine en cache)
    manhwa = make_cbz(mangas, "Gamma - Tome 1", seed=4)
    store.set_series_meta("gamma", {"country": "KR"})
    assert _open(window, qtbot, manhwa).manga_mode is False
    # BD trouvee a la BnF : lue de gauche a droite, manga traduit : de droite a gauche
    bd = make_cbz(mangas, "Lou ! Sonata Volume 1", seed=6)
    store.set_series_meta("lou sonata", {"source": "bnf", "format": "bd"})
    assert _open(window, qtbot, bd).manga_mode is False
    translated = make_cbz(mangas, "Epsilon - Tome 1", seed=7)
    store.set_series_meta("epsilon", {"source": "bnf", "format": "manga"})
    assert _open(window, qtbot, translated).manga_mode is True


def test_settings_bar_is_compact(window, qtbot, mangas, store):
    store.set_reader_pref("fit_mode", 0)       # ancien « fenetre » : fusionne avec la hauteur
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1"))
    labels = [b.text() for b in reader.hud_bar.findChildren(QPushButton)]
    assert labels == ["Double page", "Manga", "Recadrage auto", "", "Décalage"]

    # ajustement : une icone (double fleche) sans libelle, deux etats
    fit = reader.chip_fit
    assert reader.fit_mode == FIT_HEIGHT and not fit.icon().isNull()
    assert fit.toolTip().startswith("Ajuster à la hauteur")
    before = fit.icon().pixmap(32, 32).toImage()
    fit.click()
    assert reader.fit_mode == FIT_WIDTH and fit.toolTip().startswith("Ajuster à la largeur")
    assert fit.icon().pixmap(32, 32).toImage() != before
    fit.click()
    assert reader.fit_mode == FIT_HEIGHT and store.reader_pref("fit_mode") == FIT_HEIGHT

    # l'aide et l'Ambilight ont quitte la barre mais gardent leur raccourci
    QApplication.sendEvent(reader, QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier))
    assert reader.ambilight and store.reader_pref("ambilight") is True


def test_height_fit_keeps_the_whole_page_on_screen(window, qtbot, mangas, store):
    store.set_reader_pref("double_page", False)
    path = make_cbz(mangas, "Planche - Tome 1", pages=2, size=(900, 300))
    reader = _open(window, qtbot, path)
    window.reader_window.resize(1200, 800)
    reader.repaint()
    _y, h, vh = reader._view_geom
    assert h < vh and reader.pan == QPoint(0, 0)   # reduite a la largeur, sans deborder


def test_pdf_is_readable(window, qtbot, mangas):
    reader = _open(window, qtbot, make_pdf(mangas, "Pluto - Tome 1", pages=3))
    assert reader.total == 3
    assert max(reader.cache[0].width(), reader.cache[0].height()) >= 1400


def test_help_overlay_escape_only_closes_help(window, qtbot, mangas):
    reader = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1"))
    QApplication.sendEvent(reader, QKeyEvent(QEvent.KeyPress, Qt.Key_F1, Qt.NoModifier))
    assert reader._help.isVisible()
    QApplication.sendEvent(reader, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not reader._help.isVisible() and window.reader is reader


def test_instance_message_opens_file_in_existing_window(window, qtbot, mangas):
    first = _open(window, qtbot, make_cbz(mangas, "Alpha - Tome 1", seed=1))
    second = make_cbz(mangas, "Alpha - Tome 2", seed=2)
    window.handle_instance_message({"open": second})
    assert window.reader is not first and window.reader.path == second


def test_page_cache_stays_bounded_when_going_back_and_forth(qapp, monkeypatch):
    """Aller-retour dans un tome : les pages voisines de la page courante ne
    sont pas evincees sur le moment, mais doivent le rester plus tard (elles
    restaient autrefois en memoire pour toute la seance)."""
    from PySide6.QtGui import QImage

    from beheread.ui.reader import page_cache
    from beheread.ui.reader.components import _PageSignals

    class Loader:
        def __init__(self, _archive, index):
            self.index, self.signals = index, _PageSignals()

    class Pool:
        def start(self, loader):
            loader.signals.loaded.emit(loader.index, QImage(1, 1, QImage.Format_RGB32))

    monkeypatch.setattr(page_cache, "PageLoader", Loader)
    cache = page_cache.PageCache(None, 200)
    cache.pool = Pool()
    page = 50
    for step in [1, 1, 2, -1, -2, -1, 1] * 300:
        page = max(0, min(199, page + step))
        cache.ensure_around(page)
    assert len(cache.images) <= page_cache.CACHE_LIMIT
    assert set(cache.images) == set(cache._order)



def test_closing_on_the_first_pages_forgets_the_progress(window, qtbot, mangas, store):
    """Refermer un tome sur sa page 1, 2 ou 3 : il n'est pas commence, sa
    progression est effacee. Plus loin, elle est gardee ; un tome deja
    termine le reste."""
    path = make_cbz(mangas, "Alpha - Tome 1", pages=8, seed=1)
    store.set_reader_pref("double_page", False)
    reader = _open(window, qtbot, path)
    reader._go_to(2)
    reader.close_reader()
    assert store.get_progress(path) is None

    reader = _open(window, qtbot, path)
    reader._go_to(3)
    reader.close_reader()
    assert store.get_progress(path)[0] == 3

    store.set_progress(path, 7, 8, True)
    window.open_manga(path)            # rouvert sur sa derniere page
    reader = window.reader
    reader._go_to(1)
    reader.close_reader()
    assert store.get_progress(path) == (1, 8, True)


def test_end_card_opens_the_volume_on_babelio(window, qtbot, mangas, store, monkeypatch):
    from pathlib import Path

    from PySide6.QtGui import QDesktopServices
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))
    path = make_cbz(mangas, "Alpha - Tome 2", pages=3)
    reader = _open(window, qtbot, path)
    for _ in range(3):
        reader.next_page(animate=False)
    assert reader.end_card.isVisible()
    reader.end_babelio_btn.click()
    assert len(opened) == 1 and opened[0].isLocalFile()
    page = Path(opened[0].toLocalFile()).read_text(encoding="utf-8")
    assert 'action="https://www.babelio.com/recherche.php"' in page
    assert 'name="Recherche" value="alpha tome 2"' in page
