"""Briques de style communes aux feuilles de style locales.

Les valeurs (rayons, tailles de texte, espacements) et le bouton principal
etaient recopies dans une quinzaine de feuilles de style ; elles sont
definies ici une seule fois. Comme pour theme.py, les couleurs d'accent se
lisent au moment de construire la feuille (« theme.ACCENT »), jamais a
l'import."""

from beheread.ui import theme

# rayons d'angle : champs et petits boutons, boutons et cartes, pilules
RADIUS_SM, RADIUS_MD, RADIUS_PILL = 6, 8, 16

# tailles de texte (px) : aide et legendes, corps, sous-titres, titres
TEXT_SM, TEXT_MD, TEXT_LG, TEXT_XL = 12, 13, 15, 20

# espacements (px) : de la marge serree au gouttiere de page
SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG = 4, 8, 14, 24


def primary_button(selector: str, extra: str = "") -> str:
    """Bouton principal : plein, a la couleur d'accentuation, plus clair au
    survol. `selector` : « QPushButton#primary » ; `extra` : declarations
    propres a l'usage (marges, taille du texte)."""
    return f"""
        {selector} {{
            color: {theme.ON_ACCENT}; background: {theme.ACCENT}; border: none;
            font-weight: 700; {extra}
        }}
        {selector}:hover {{ background: {theme.ACCENT_HOVER}; }}
        {selector}:disabled {{ color: rgba(128, 128, 128, 170); background: rgba(128, 128, 128, 50); }}
    """
