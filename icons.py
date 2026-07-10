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


def folder_cog(color) -> QIcon:
    """Dossier surmonte d'un petit engrenage : gestion des dossiers sources."""
    def draw(p):
        _folder_base(p)
        # engrenage compact pose sur le dossier
        cx, cy, r = 38.0, 38.0, 6.0
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        for ang in range(0, 360, 45):
            a = math.radians(ang)
            p.drawLine(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)),
                       QPointF(cx + (r + 4) * math.cos(a), cy + (r + 4) * math.sin(a)))
    return _make(draw, color)


def x_mark(color) -> QIcon:
    """Croix fine pour retirer un element d'une liste."""
    def draw(p):
        p.drawLine(20, 20, 44, 44)
        p.drawLine(44, 20, 20, 44)
    return _make(draw, color)


def refresh(color) -> QIcon:
    def draw(p):
        rect = QRectF(14, 14, 36, 36)
        p.drawArc(rect, 40 * 16, 250 * 16)
        # pointe de fleche a l'extremite de l'arc (~40 degres)
        p.drawLine(QPointF(46.0, 22.0), QPointF(52.0, 20.0))
        p.drawLine(QPointF(46.0, 22.0), QPointF(46.5, 28.5))
    return _make(draw, color)


def sun(color) -> QIcon:
    def draw(p):
        p.drawEllipse(QRectF(24, 24, 16, 16))
        for x1, y1, x2, y2 in ((32, 8, 32, 15), (32, 49, 32, 56),
                               (8, 32, 15, 32), (49, 32, 56, 32),
                               (15, 15, 20, 20), (44, 44, 49, 49),
                               (49, 15, 44, 20), (20, 44, 15, 49)):
            p.drawLine(x1, y1, x2, y2)
    return _make(draw, color)


def moon(color) -> QIcon:
    def draw(p):
        path = QPainterPath()
        path.moveTo(40, 12)
        path.arcTo(QRectF(12, 12, 40, 40), 100, 250)
        path.arcTo(QRectF(22, 8, 32, 32), -20, -160)
        p.drawPath(path)
    return _make(draw, color)


def grid(color) -> QIcon:
    def draw(p):
        for x in (12, 36):
            for y in (12, 36):
                p.drawRoundedRect(QRectF(x, y, 16, 16), 3, 3)
    return _make(draw, color)


def list_view(color) -> QIcon:
    def draw(p):
        for y in (16, 32, 48):
            p.drawEllipse(QRectF(11, y - 2.5, 5, 5))
            p.drawLine(24, y, 52, y)
    return _make(draw, color)


def layers(color) -> QIcon:
    def draw(p):
        p.drawPolygon([QPointF(32, 10), QPointF(54, 22), QPointF(32, 34), QPointF(10, 22)])
        path = QPainterPath()
        path.moveTo(10, 32)
        path.lineTo(32, 44)
        path.lineTo(54, 32)
        p.drawPath(path)
        path2 = QPainterPath()
        path2.moveTo(10, 42)
        path2.lineTo(32, 54)
        path2.lineTo(54, 42)
        p.drawPath(path2)
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
