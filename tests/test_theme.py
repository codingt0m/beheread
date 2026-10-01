"""Tests de la palette (theme.py)."""

import pytest

from beheread.ui import theme

GREEN = "#2d9959"


def _state():
    return {k: getattr(theme, k) for k in ("ACCENT", "ACCENT_HOVER", "ACCENT_DIM",
                                           "ACCENT_SOFT", "ON_ACCENT", "FINISHED")}


def test_theme_colors_are_all_paintable():
    """Toutes les couleurs de la palette doivent etre lisibles par QColor
    (les « rgba(...) » des feuilles de style passent par theme.qcolor)."""
    for mode in ("dark", "light"):
        for name, value in theme.colors(mode).items():
            assert theme.qcolor(value).isValid(), (mode, name, value)
    assert theme.qcolor("rgba(255, 255, 255, 22)").alpha() == 22


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("value", [None, "", "vert", "#12345", 12, theme.DEFAULT_ACCENT, "#C0392B"])
def test_default_accent_keeps_the_original_colors(mode, value):
    """Sans preference (ou avec une valeur abimee), et apres « Reinitialiser »,
    on retrouve exactement les couleurs d'origine dans les deux themes."""
    theme.set_accent(GREEN, mode)
    theme.set_accent(value, mode)
    assert _state() == {
        "ACCENT": "#c0392b", "ACCENT_HOVER": "#d14433",
        "ACCENT_DIM": "rgba(192, 57, 43, 170)", "ACCENT_SOFT": "rgba(192, 57, 43, 55)",
        "ON_ACCENT": "#f5f0ee", "FINISHED": "#4cc26b"}
    assert theme.ACCENT_CHOICE == theme.DEFAULT_ACCENT


def test_accent_drives_every_derived_color():
    theme.set_accent(GREEN, "dark")
    assert theme.ACCENT == theme.ACCENT_CHOICE == GREEN
    assert theme.ACCENT_DIM == "rgba(45, 153, 89, 170)"
    assert theme.ACCENT_SOFT == "rgba(45, 153, 89, 55)"
    assert theme.ACCENT_HOVER not in (GREEN, "#d14433")
    assert theme.qcolor(theme.ACCENT_DIM).alpha() == 170


def test_green_accent_moves_finished_away_from_green():
    """« En cours » porte l'accent : avec un accent vert, « termine » ne peut
    pas rester vert."""
    for accent in (GREEN, "#2ecc71", "#4cc26b"):
        theme.set_accent(accent, "dark")
        assert theme.FINISHED != theme.DEFAULT_FINISHED, accent
        assert theme.distance(theme.FINISHED, theme.ACCENT) >= theme.MIN_DISTANCE
    for accent in ("#2f7fd6", "#8e5bd6", "#d9772b", "#808080"):
        theme.set_accent(accent, "dark")
        assert theme.FINISHED == theme.DEFAULT_FINISHED, accent


@pytest.mark.parametrize("accent", ["#fff3a0", "#ffffff", "#0a1040", "#000000", "#808080",
                                    "#2ecc71", "#ff00ff", "#00ffff", "#c08416"])
@pytest.mark.parametrize("mode", ["dark", "light"])
def test_any_accent_stays_readable(accent, mode):
    """Quelle que soit la couleur choisie, l'accent affiche contraste avec le
    fond du theme, et le texte pose sur un bouton d'accent reste lisible."""
    theme.set_accent(accent, mode)
    assert theme.ACCENT_CHOICE == accent   # le choix lui-meme n'est pas modifie
    c = theme.colors(mode)
    for background in (c["window"], c["panel"]):
        assert theme.contrast(theme.ACCENT, background) >= theme.MIN_CONTRAST - 0.01
    assert theme.contrast(theme.ON_ACCENT, theme.ACCENT) >= theme.MIN_CONTRAST


def test_bounding_only_touches_unreadable_colors():
    assert theme.bounded_accent(GREEN, "dark") == theme.bounded_accent(GREEN, "light") == GREEN
    pale = theme.bounded_accent("#fff3a0", "light")
    assert pale != "#fff3a0" and theme.luminance(pale) < theme.luminance("#fff3a0")
    assert theme.bounded_accent("#fff3a0", "dark") == "#fff3a0"
    night = theme.bounded_accent("#0a1040", "dark")
    assert night != "#0a1040" and theme.luminance(night) > theme.luminance("#0a1040")
    assert theme.bounded_accent("#0a1040", "light") == "#0a1040"


def test_color_distance_and_contrast():
    assert theme.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert theme.distance("#3fa35f", "#3fa35f") == 0
    # rose et vert : nets en vision normale, proches pour un deuteranope
    assert theme.distance("#d6457f", "#3fa35f") > theme.MIN_DISTANCE
    assert theme.distance("#d6457f", "#3fa35f", "deutan") < theme.MIN_CVD_DISTANCE
    assert theme.separation("#d6457f", "#3fa35f") < 1 <= theme.separation(
        "#d6457f", "#3fa35f", cvd=False)
    assert theme.pick_distinct(["#3fa35f", "#3987e5"], ["#2e9e5b"]) == "#3987e5"
