"""Palette de couleurs partagee par toute l'interface (bibliotheque, lecteur,
fenetre principale), avec bascule clair/sombre. L'accent (rouge "Behelit")
reste identique dans les deux modes."""

ACCENT = "#c0392b"
ACCENT_DIM = "rgba(192, 57, 43, 170)"
FINISHED = "#4cc26b"   # vert "termine", inchange dans les deux modes

DARK = {
    "window": "#1b1e24",
    "panel": "#14161b",
    "text": "#d7dbe2",
    "text_dim": "#8b93a1",
    "text_disabled": "#5f6773",
    "border": "#2b2f36",
    "button": "#262a32",
    "button_hover": "#333844",
    "hud_bg": "rgba(15, 17, 22, 190)",
    "reader_bg": "#000000",
    "list_bg": "#1b1e24",
    "cover_placeholder": "#2b2f36",
    "cover_text": "#6c7380",
    "cover_border": "rgba(255, 255, 255, 30)",
    "selection": "rgba(255, 255, 255, 22)",
    "track_bg": "rgba(0, 0, 0, 160)",
}

LIGHT = {
    "window": "#f1efec",
    "panel": "#ffffff",
    "text": "#2a2a2a",
    "text_dim": "#6b655e",
    "text_disabled": "#a39b92",
    "border": "#ddd8d2",
    "button": "#eae6e1",
    "button_hover": "#ddd6cd",
    "hud_bg": "rgba(255, 255, 255, 215)",
    "reader_bg": "#e8e4e0",
    "list_bg": "#f1efec",
    "cover_placeholder": "#e0dbd4",
    "cover_text": "#8a8078",
    "cover_border": "rgba(0, 0, 0, 25)",
    "selection": "rgba(0, 0, 0, 18)",
    "track_bg": "rgba(0, 0, 0, 60)",
}


def colors(mode: str) -> dict:
    return LIGHT if mode == "light" else DARK


def qcolor(value: str):
    """QColor a partir d'une couleur de la palette. Les feuilles de style Qt
    comprennent « rgba(r, g, b, a) », mais pas QColor : sans cette
    conversion, ces couleurs devenaient un noir opaque une fois peintes au
    QPainter (selection, contour des couvertures, fond des barres)."""
    from PySide6.QtGui import QColor
    v = value.strip()
    if v.startswith("rgba(") and v.endswith(")"):
        r, g, b, a = (int(float(x)) for x in v[5:-1].split(","))
        return QColor(r, g, b, a)
    return QColor(v)
