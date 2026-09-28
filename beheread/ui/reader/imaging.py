"""Traitements d'image du lecteur, sans etat (fonctions sur QImage) :
detection des marges a rogner et couleur moyenne pour l'Ambilight."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage

from beheread.ui.reader.constants import AMBIENT_DARKEN


def compute_content_rect(img: QImage):
    """Detecte le rectangle de contenu en rognant les bords quasi uniformes
    (marges blanches OU noires). Travaille sur une version reduite en
    niveaux de gris pour rester rapide."""
    w0, h0 = img.width(), img.height()
    if w0 < 40 or h0 < 40:
        return None
    sw = 120
    sh = max(1, round(h0 * sw / w0))
    small = img.scaled(sw, sh, Qt.IgnoreAspectRatio,
                       Qt.FastTransformation).convertToFormat(QImage.Format_Grayscale8)

    def gray(x, y):
        return small.pixel(x, y) & 0xFF

    # couleur de fond = mediane des quatre coins (gere marges claires/sombres)
    corners = sorted([gray(0, 0), gray(sw - 1, 0), gray(0, sh - 1), gray(sw - 1, sh - 1)])
    bg = corners[1]
    thresh = 32
    min_pixels = max(2, sw // 60)   # ignore quelques pixels de bruit isoles

    def row_has_content(y):
        n = sum(1 for x in range(sw) if abs(gray(x, y) - bg) > thresh)
        return n > min_pixels

    def col_has_content(x, y0, y1):
        n = sum(1 for y in range(y0, y1 + 1) if abs(gray(x, y) - bg) > thresh)
        return n > min_pixels

    top = 0
    while top < sh and not row_has_content(top):
        top += 1
    if top >= sh:
        return None   # page uniforme (page blanche/noire) : pas de recadrage
    bottom = sh - 1
    while bottom > top and not row_has_content(bottom):
        bottom -= 1
    left = 0
    while left < sw and not col_has_content(left, top, bottom):
        left += 1
    right = sw - 1
    while right > left and not col_has_content(right, top, bottom):
        right -= 1

    # remise a l'echelle vers l'image pleine resolution + petite marge
    fx, fy = w0 / sw, h0 / sh
    pad_x, pad_y = round(w0 * 0.01), round(h0 * 0.01)
    x = max(0, int(left * fx) - pad_x)
    y = max(0, int(top * fy) - pad_y)
    rx = min(w0, int((right + 1) * fx) + pad_x)
    ry = min(h0, int((bottom + 1) * fy) + pad_y)
    cw, ch = rx - x, ry - y
    if cw <= 0 or ch <= 0:
        return None
    # recadrage negligeable (moins de 3% rogne sur chaque axe) : inutile
    if cw >= w0 * 0.97 and ch >= h0 * 0.97:
        return None
    return QRect(x, y, cw, ch)


def average_color(img: QImage) -> QColor:
    """Couleur moyenne approximative de l'image : Qt lisse en la reduisant
    a 1x1 pixel, bien plus rapide qu'un parcours manuel des pixels."""
    small = img.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return QColor(small.pixel(0, 0))


def darken(color: QColor, factor: float = AMBIENT_DARKEN) -> QColor:
    return QColor(int(color.red() * factor), int(color.green() * factor),
                  int(color.blue() * factor))
