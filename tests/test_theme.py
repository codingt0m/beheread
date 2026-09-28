"""Tests de la palette (theme.py)."""

from beheread.ui import theme


def test_theme_colors_are_all_paintable():
    """Toutes les couleurs de la palette doivent etre lisibles par QColor
    (les « rgba(...) » des feuilles de style passent par theme.qcolor)."""
    for mode in ("dark", "light"):
        for name, value in theme.colors(mode).items():
            assert theme.qcolor(value).isValid(), (mode, name, value)
    assert theme.qcolor("rgba(255, 255, 255, 22)").alpha() == 22
