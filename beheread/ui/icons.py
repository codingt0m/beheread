"""Icones vectorielles minimalistes dessinees avec QPainter, sans aucune
dependance externe ni fichier d'asset. Chaque fonction renvoie un QIcon
dessine dans la couleur demandee, ce qui permet de les re-teinter a la
volee lors d'un changement de theme clair/sombre."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_CANVAS = 64          # dessine en grand puis reduit par Qt (net en HiDPI)
_STROKE = 5.0


def _make(draw_fn, color) -> QIcon:
    pm = QPixmap(_CANVAS, _CANVAS)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), _STROKE)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    draw_fn(p)
    p.end()
    return QIcon(pm)


def swatch(color, ring=None) -> QIcon:
    """Pastille de couleur pleine (choix de la couleur d'accentuation) ;
    `ring` : couleur de l'anneau qui entoure la pastille selectionnee."""
    pm = QPixmap(_CANVAS, _CANVAS)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(32, 32), 22, 22)
    if ring:
        p.setPen(QPen(QColor(ring), 4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(32, 32), 29, 29)
    p.end()
    return QIcon(pm)


def _folder_base(p):
    path = QPainterPath()
    path.moveTo(10, 22)
    path.lineTo(10, 50)
    path.lineTo(54, 50)
    path.lineTo(54, 26)
    path.lineTo(30, 26)
    path.lineTo(25, 18)
    path.lineTo(14, 18)
    path.lineTo(10, 22)
    p.drawPath(path)


def folder_plus(color) -> QIcon:
    def draw(p):
        _folder_base(p)
        p.drawLine(32, 32, 32, 44)
        p.drawLine(26, 38, 38, 38)
    return _make(draw, color)


def folder_minus(color) -> QIcon:
    def draw(p):
        _folder_base(p)
        p.drawLine(26, 38, 38, 38)
    return _make(draw, color)


def folder(color) -> QIcon:
    """Dossier simple : gestion des dossiers sources."""
    return _make(_folder_base, color)


def x_mark(color) -> QIcon:
    """Croix fine pour retirer un element d'une liste."""
    def draw(p):
        p.drawLine(20, 20, 44, 44)
        p.drawLine(44, 20, 20, 44)
    return _make(draw, color)


def refresh(color) -> QIcon:
    """Fleche circulaire : un arc de trois quarts de tour dans le sens des
    aiguilles d'une montre, prolonge jusqu'a une pointe en equerre en haut a
    droite."""
    def draw(p):
        r = 21.0                                   # rayon de l'arc, centre (32, 32)
        tip = QPointF(32 + r, 23.0)                # sommet de la pointe
        path = QPainterPath()
        path.moveTo(32 + r, 32)
        path.arcTo(QRectF(32 - r, 32 - r, 2 * r, 2 * r), 0, -270)   # jusqu'en haut
        # du haut du cercle vers la pointe : on quitte l'arc en douceur
        path.cubicTo(QPointF(38.0, 11.0), QPointF(43.5, 13.5), QPointF(47.5, 17.5))
        path.lineTo(tip)
        p.drawPath(path)
        p.drawPolyline([QPointF(tip.x(), 11.0), tip, QPointF(tip.x() - 12.0, tip.y())])
    return _make(draw, color)


def search(color) -> QIcon:
    def draw(p):
        p.drawEllipse(QRectF(12, 12, 28, 28))
        p.drawLine(45, 45, 54, 54)
    return _make(draw, color)


def chevron_left(color) -> QIcon:
    def draw(p):
        p.drawPolyline([QPointF(38, 16), QPointF(20, 32), QPointF(38, 48)])
    return _make(draw, color)


def expand(color) -> QIcon:
    """Icone plein ecran : quatre coins qui s'ecartent."""
    def draw(p):
        arm = 12
        corners = [
            (14, 14, 1, 1),    # haut-gauche
            (50, 14, -1, 1),   # haut-droite
            (14, 50, 1, -1),   # bas-gauche
            (50, 50, -1, -1),  # bas-droite
        ]
        for x, y, dx, dy in corners:
            p.drawLine(QPointF(x, y), QPointF(x + arm * dx, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + arm * dy))
    return _make(draw, color)


def cog(color) -> QIcon:
    """Engrenage : preferences. Roue dentee tracee d'un seul contour (dents
    larges en trapeze) autour d'un moyeu, et non des traits qui rayonnent
    d'un cercle : a petite taille, ceux-ci se lisaient comme un soleil."""
    def draw(p):
        cx, cy = 32.0, 32.0
        teeth = 6                          # peu de dents : lisible a 18 px
        outer, inner = 24.0, 17.0          # sommet et pied des dents
        step = 360.0 / teeth
        top, base = step * 0.20, step * 0.32   # demi-largeurs angulaires d'une dent

        def point(radius, degrees):
            a = math.radians(degrees - 90)   # premiere dent en haut
            return QPointF(cx + radius * math.cos(a), cy + radius * math.sin(a))

        outline = []
        for i in range(teeth):
            mid = i * step
            outline += [point(inner, mid - base), point(outer, mid - top),
                        point(outer, mid + top), point(inner, mid + base)]
        p.drawPolygon(outline)
        p.drawEllipse(QRectF(cx - 7, cy - 7, 14, 14))
    return _make(draw, color)


def bar_chart(color) -> QIcon:
    """Histogramme : statistiques de lecture."""
    def draw(p):
        p.drawLine(10, 52, 54, 52)
        for x, top in ((17, 36), (29, 22), (41, 30)):
            p.drawRoundedRect(QRectF(x, top, 7, 52 - top), 2, 2)
    return _make(draw, color)
