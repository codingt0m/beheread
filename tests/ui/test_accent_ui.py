"""Tests d'interface de la couleur d'accentuation (preferences, application
a la fenetre, logo re-teinte, couleurs des statistiques)."""

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QColorDialog

from beheread.ui import appicon, stats_view, theme
from beheread.ui.library.dialogs import ACCENT_PRESETS, PreferencesDialog

GREEN = dict(ACCENT_PRESETS)["Vert"]


def _prefs(store, qtbot):
    dlg = PreferencesDialog(store, theme.colors(store.ui_pref("theme", "dark")), {})
    qtbot.addWidget(dlg)
    return dlg


def _logo_color(window):
    """Couleur dominante du logo de l'en-tete (un pixel du corps du dessin)."""
    image = window.library.logo_label.pixmap().toImage()
    return image.pixelColor(image.width() // 2, image.height() * 3 // 4)


def test_choosing_an_accent_recolors_the_whole_window(window, qtbot, store):
    lib = window.library
    assert theme.DEFAULT_ACCENT in lib.title_label.text()
    red_logo = _logo_color(window)
    assert red_logo.hsvHue() < 20 or red_logo.hsvHue() > 335

    dlg = _prefs(store, qtbot)
    assert dlg._swatches[theme.DEFAULT_ACCENT].isChecked() and not dlg.accent_reset.isEnabled()
    dlg._swatches[GREEN].click()
    assert dlg._swatches[GREEN].isChecked() and dlg.accent_reset.isEnabled()
    assert store.ui_pref("accent") is None   # rien n'est ecrit avant « Enregistrer »
    dlg.save()
    window.apply_preferences()

    assert store.ui_pref("accent") == GREEN and theme.ACCENT == GREEN
    assert GREEN in lib.title_label.text() and theme.DEFAULT_ACCENT not in lib.title_label.text()
    assert theme.ACCENT_SOFT in lib.header.styleSheet()
    assert "192, 57, 43" not in lib.header.styleSheet()
    assert QApplication.palette().highlight().color() == QColor(GREEN)
    assert abs(_logo_color(window).hsvHue() - QColor(GREEN).hsvHue()) < 15
    assert window.windowIcon().cacheKey() == appicon.app_icon().cacheKey()
    # le changement de theme conserve l'accent
    store.set_ui_pref("theme", "light")
    window.apply_preferences()
    assert theme.ACCENT == GREEN and GREEN in lib.title_label.text()


def test_reset_restores_the_original_accent(window, qtbot, store):
    store.set_ui_pref("accent", GREEN)
    window.apply_preferences()
    assert theme.ACCENT == GREEN

    dlg = _prefs(store, qtbot)
    assert dlg._swatches[GREEN].isChecked()
    dlg.accent_reset.click()
    assert dlg._swatches[theme.DEFAULT_ACCENT].isChecked() and not dlg.accent_reset.isEnabled()
    dlg.save()
    window.apply_preferences()

    assert store.ui_pref("accent") is None
    assert theme.ACCENT == theme.DEFAULT_ACCENT and theme.FINISHED == theme.DEFAULT_FINISHED
    assert theme.DEFAULT_ACCENT in window.library.title_label.text()
    hue = _logo_color(window).hsvHue()
    assert hue < 20 or hue > 335


def test_custom_accent_and_readability_hint(qtbot, store, monkeypatch):
    dlg = _prefs(store, qtbot)
    base_hint = dlg.accent_hint.text()
    monkeypatch.setattr(QColorDialog, "getColor",
                        staticmethod(lambda *a, **k: QColor("#0a1040")))
    dlg.accent_custom.click()
    assert dlg._accent == "#0a1040"
    assert not any(b.isChecked() for b in dlg._swatches.values())
    assert not dlg.accent_custom.icon().isNull()
    assert "éclaircie" in dlg.accent_hint.text()       # trop sombre pour le theme sombre
    dlg.theme.setCurrentIndex(1)                        # theme clair : lisible telle quelle
    assert dlg.accent_hint.text() == base_hint
    # dialogue de couleur annule : le choix ne bouge pas
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a, **k: QColor()))
    dlg.accent_custom.click()
    assert dlg._accent == "#0a1040"
    dlg.save()
    assert store.ui_pref("accent") == "#0a1040"


def test_corrupted_accent_preference_falls_back_to_default(window, qtbot, store):
    store.set_ui_pref("accent", "pas une couleur")
    window.apply_preferences()
    assert theme.ACCENT == theme.DEFAULT_ACCENT
    assert _prefs(store, qtbot)._swatches[theme.DEFAULT_ACCENT].isChecked()


def test_icon_tint_only_changes_the_red_pixels(qapp):
    image = QImage(3, 1, QImage.Format_ARGB32)
    image.setPixelColor(0, 0, QColor("#e01010"))        # rouge du dessin
    image.setPixelColor(1, 0, QColor("#3a8fd0"))        # oeil bleu
    image.setPixelColor(2, 0, QColor(224, 16, 16, 0))   # transparent
    out = appicon.tinted(image, QColor(GREEN))
    assert abs(out.pixelColor(0, 0).hsvHue() - QColor(GREEN).hsvHue()) <= 2
    assert out.pixelColor(0, 0).value() == QColor("#e01010").value()   # relief conserve
    assert out.pixelColor(1, 0) == QColor("#3a8fd0")
    assert out.pixelColor(2, 0).alpha() == 0
    # un accent gris desature le dessin au lieu de le laisser rouge
    assert appicon.tinted(image, QColor("#808080")).pixelColor(0, 0).saturation() == 0

    default_icon = appicon.app_icon()
    assert not default_icon.isNull() and appicon.app_icon() is default_icon   # mis en cache
    theme.set_accent(GREEN)
    green_icon = appicon.app_icon()
    assert green_icon.cacheKey() != default_icon.cacheKey()
    assert not green_icon.pixmap(QSize(32, 32)).isNull()


def test_presets_are_readable_as_is_in_both_themes():
    for label, accent in ACCENT_PRESETS:
        for mode in ("dark", "light"):
            assert theme.bounded_accent(accent, mode) == accent, (label, mode)
    assert ACCENT_PRESETS[0][1] == theme.DEFAULT_ACCENT


def test_stats_colors_stay_distinct_for_any_accent():
    assert stats_view.data_colors("dark") == {
        "activity": "#c0392b", "reading": "#c0392b", "finished": "#3fa35f", "unread": "#3987e5"}
    assert stats_view.data_colors("light")["unread"] == "#2a78d6"
    for _label, accent in ACCENT_PRESETS:
        for mode in ("dark", "light"):
            theme.set_accent(accent, mode)
            dc = stats_view.data_colors(mode)
            assert dc["reading"] == dc["activity"] == theme.ACCENT
            # « en cours » touche les deux autres parts dans la barre empilee
            assert theme.separation(dc["finished"], dc["reading"]) >= 1, (accent, mode, dc)
            assert theme.separation(dc["unread"], dc["reading"]) >= 1, (accent, mode, dc)
            assert theme.distance(dc["finished"], dc["unread"]) >= theme.MIN_DISTANCE
