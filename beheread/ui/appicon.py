"""Icone de l'application (fenetres, logo de l'en-tete), re-teintee dans la
couleur d'accentuation choisie.

Le fichier icon.ico est un dessin rouge : seuls ses pixels rouges changent de
teinte, l'oeil bleu et la calotte doree restent tels quels. L'icone de
l'executable, des raccourcis et des fichiers associes est lue par Windows
dans Beheread.exe et garde donc la couleur d'origine."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap

from beheread.config import resource_path
from beheread.ui import theme

_SIZE = 128                    # largement assez pour la barre des taches et Alt+Tab
_RED_FROM, _RED_TO = 335, 20   # plage de teintes (degres) consideree comme « rouge »
_RED_HUE = 0                   # teinte du rouge du dessin, qui prend celle de l'accent

_cached = (None, None)         # (accent, QIcon) : le calcul prend quelques dizaines de ms


def app_icon() -> QIcon:
    """Icone de Beheread pour l'accent courant (theme.ACCENT_CHOICE : le
    choix de l'utilisateur, identique en theme clair et sombre)."""
    global _cached
    accent = theme.ACCENT_CHOICE
    if _cached[0] != accent:
        _cached = (accent, _build(accent))
    return _cached[1]


def _build(accent) -> QIcon:
    path = resource_path("icon.ico")
    if not path.exists():
        return QIcon()
    icon = QIcon(str(path))
    if accent == theme.DEFAULT_ACCENT:
        return icon
    image = icon.pixmap(QSize(256, 256), 1.0).toImage().scaled(
        _SIZE, _SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return QIcon(QPixmap.fromImage(tinted(image, QColor(accent))))


def tinted(image: QImage, accent: QColor) -> QImage:
    """Copie de `image` dont les pixels rouges prennent la teinte de `accent`
    (et sa saturation, pour qu'un accent gris donne une icone grise) ; le
    relief du dessin, porte par la clarte, est conserve."""
    shift = accent.hsvHue() - _RED_HUE if accent.hsvHue() >= 0 else 0
    saturation = min(1.0, accent.hsvSaturationF()
                     / QColor(theme.DEFAULT_ACCENT).hsvSaturationF())
    out = image.convertToFormat(QImage.Format_ARGB32)
    for y in range(out.height()):
        for x in range(out.width()):
            c = out.pixelColor(x, y)
            hue = c.hsvHue()   # -1 pour un pixel sans teinte (gris, noir, blanc)
            if c.alpha() == 0 or hue < 0 or _RED_TO < hue < _RED_FROM:
                continue
            out.setPixelColor(x, y, QColor.fromHsvF(
                ((hue + shift) % 360) / 360.0, c.hsvSaturationF() * saturation,
                c.valueF(), c.alphaF()))
    return out
