"""Palette de couleurs partagee par toute l'interface (bibliotheque, lecteur,
fenetre principale), avec bascule clair/sombre.

L'accent (rouge "Behelit" par defaut) est personnalisable dans les
preferences : set_accent() recalcule l'accent et tout ce qui en decoule
(survol, variantes translucides, texte pose dessus, couleur « termine »).
Ces valeurs se lisent toujours sous la forme « theme.ACCENT » au moment de
peindre ou de construire une feuille de style : un « from theme import
ACCENT » figerait l'ancienne valeur."""

import colorsys
import re

DEFAULT_ACCENT = "#c0392b"
DEFAULT_FINISHED = "#4cc26b"   # vert "termine"
# « termine » doit rester distinct de « en cours » (qui porte l'accent) : si
# l'accent choisi est lui-meme vert, on prend la couleur suivante
FINISHED_CANDIDATES = (DEFAULT_FINISHED, "#4a9fe8")

# valeurs courantes (recalculees par set_accent)
ACCENT_CHOICE = DEFAULT_ACCENT            # choix de l'utilisateur, avant bornage
ACCENT = DEFAULT_ACCENT                   # accent affiche, lisible sur le theme courant
ACCENT_HOVER = "#d14433"                  # survol d'un bouton plein
ACCENT_DIM = "rgba(192, 57, 43, 170)"
ACCENT_SOFT = "rgba(192, 57, 43, 55)"     # fond d'un bouton d'en-tete actif
ON_ACCENT = "#f5f0ee"                     # texte pose sur un fond d'accent
FINISHED = DEFAULT_FINISHED

# contraste minimal de l'accent avec le fond (titre « BEHE », contours de
# focus, icones actives) et du texte pose sur un bouton d'accent
MIN_CONTRAST = 3.0
# ecart minimal (OKLab x100) entre deux couleurs qui portent un sens
# different, en vision normale et en vision daltonienne simulee
MIN_DISTANCE = 15.0
MIN_CVD_DISTANCE = 8.0
_ON_ACCENT_LIGHT, _ON_ACCENT_DARK = "#f5f0ee", "#16181d"

# simulation du daltonisme (Machado, Oliveira & Fernandes 2009, severite 1),
# en RGB lineaire - le modele sur lequel MIN_CVD_DISTANCE est etalonne
_CVD = {
    "protan": ((0.152286, 1.052583, -0.204868),
               (0.114503, 0.786281, 0.099216),
               (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968),
               (0.280085, 0.672501, 0.047413),
               (-0.011820, 0.042940, 0.968881)),
}

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


# ---------------------------------------------------------------- accent

def normalize_accent(value):
    """« #rrggbb » en minuscules, ou None si la valeur n'est pas une couleur
    de cette forme (preference absente, abimee ou venue d'une autre version)."""
    if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value.strip()):
        return value.strip().lower()
    return None


def _rgb(value):
    v = value.lstrip("#")
    return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(*(round(max(0.0, min(1.0, x)) * 255) for x in (r, g, b)))


def _linear(x):
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def luminance(value) -> float:
    """Luminance relative (WCAG) d'une couleur « #rrggbb »."""
    r, g, b = (_linear(x) for x in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    """Rapport de contraste WCAG entre deux couleurs « #rrggbb » (1 a 21)."""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _oklab(r, g, b):
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def distance(a, b, vision=None) -> float:
    """Ecart percu entre deux couleurs « #rrggbb » (distance OKLab x100), en
    vision normale ou telle que la voit un daltonien (« protan », « deutan »)."""
    labs = []
    for value in (a, b):
        rgb = tuple(_linear(x) for x in _rgb(value))
        if vision:
            rgb = tuple(max(0.0, min(1.0, sum(k * x for k, x in zip(row, rgb))))
                        for row in _CVD[vision])
        labs.append(_oklab(*rgb))
    return 100 * sum((x - y) ** 2 for x, y in zip(*labs)) ** 0.5


def separation(a, b, cvd=True) -> float:
    """Marge de separation de deux couleurs : >= 1 quand elles ne se
    confondent pas, y compris (cvd) pour un daltonien."""
    margin = distance(a, b) / MIN_DISTANCE
    if cvd:
        margin = min(margin, distance(a, b, "protan") / MIN_CVD_DISTANCE,
                     distance(a, b, "deutan") / MIN_CVD_DISTANCE)
    return margin


def pick_distinct(candidates, taken, cvd=True):
    """Premiere couleur de `candidates` qui ne se confond avec aucune de
    `taken` ; a defaut, la mieux separee."""
    def margin(c):
        return min(separation(c, t, cvd) for t in taken)
    for c in candidates:
        if margin(c) >= 1:
            return c
    return max(candidates, key=margin)


def bounded_accent(value, mode: str) -> str:
    """Accent reellement affiche pour un choix de l'utilisateur : la teinte
    est conservee, la clarte est ramenee juste assez pour rester lisible sur
    le fond du theme (un jaune pale disparaitrait en clair, un bleu nuit en
    sombre). L'accent par defaut n'est pas modifie."""
    accent = normalize_accent(value) or DEFAULT_ACCENT
    # fond le plus exigeant de chaque theme : le plus proche de l'accent
    bg = colors(mode)["window"]
    if contrast(accent, bg) >= MIN_CONTRAST:
        return accent
    h, l, s = colorsys.rgb_to_hls(*_rgb(accent))
    ok = 0.0 if mode == "light" else 1.0   # clarte qui contraste a coup sur
    bad = l
    for _ in range(20):
        mid = (ok + bad) / 2
        if contrast(_hex(*colorsys.hls_to_rgb(h, mid, s)), bg) >= MIN_CONTRAST:
            ok = mid
        else:
            bad = mid
    return _hex(*colorsys.hls_to_rgb(h, ok, s))


def _hover(accent):
    if accent == DEFAULT_ACCENT:
        return "#d14433"   # valeur d'origine, a l'unite pres
    h, l, s = colorsys.rgb_to_hls(*_rgb(accent))
    return _hex(*colorsys.hls_to_rgb(h, l + 0.05 if l < 0.6 else l - 0.05, s))


def _on_accent(accent):
    # texte clair tant qu'il reste lisible (aspect d'origine), sombre sinon
    if contrast(_ON_ACCENT_LIGHT, accent) >= MIN_CONTRAST:
        return _ON_ACCENT_LIGHT
    return max((_ON_ACCENT_LIGHT, _ON_ACCENT_DARK), key=lambda c: contrast(c, accent))


def set_accent(value, mode: str = "dark"):
    """Applique la couleur d'accentuation choisie (« #rrggbb » ; None ou une
    valeur invalide = accent par defaut) pour le theme `mode`. A appeler
    avant de reconstruire les feuilles de style (voir app.apply_theme)."""
    global ACCENT_CHOICE, ACCENT, ACCENT_HOVER, ACCENT_DIM, ACCENT_SOFT, ON_ACCENT, FINISHED
    ACCENT_CHOICE = normalize_accent(value) or DEFAULT_ACCENT
    ACCENT = bounded_accent(ACCENT_CHOICE, mode)
    r, g, b = (round(x * 255) for x in _rgb(ACCENT))
    ACCENT_HOVER = _hover(ACCENT)
    ACCENT_DIM = f"rgba({r}, {g}, {b}, 170)"
    ACCENT_SOFT = f"rgba({r}, {g}, {b}, 55)"
    ON_ACCENT = _on_accent(ACCENT)
    # vision normale seulement : dans la grille, « termine » se reconnait
    # aussi a sa pastille cochee et a sa barre pleine
    FINISHED = pick_distinct(FINISHED_CANDIDATES, [ACCENT], cvd=False)
