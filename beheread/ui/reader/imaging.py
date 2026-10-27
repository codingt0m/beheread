"""Traitements d'image propres au lecteur, sans etat (fonctions sur QImage) :
couleur moyenne pour l'Ambilight. La detection des marges, partagee avec le
serveur, est dans infra/imaging.py."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from beheread.ui.reader.constants import AMBIENT_DARKEN


def average_color(img: QImage) -> QColor:
    """Couleur moyenne approximative de l'image : Qt lisse en la reduisant
    a 1x1 pixel, bien plus rapide qu'un parcours manuel des pixels."""
    small = img.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return QColor(small.pixel(0, 0))


def darken(color: QColor, factor: float = AMBIENT_DARKEN) -> QColor:
    return QColor(int(color.red() * factor), int(color.green() * factor),
                  int(color.blue() * factor))
