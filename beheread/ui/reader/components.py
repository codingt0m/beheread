"""Composants du lecteur : barre de pages cliquable, chargement de page en
arriere-plan, recherche et prechauffage du tome suivant."""

import logging
from typing import NamedTuple

from PySide6.QtCore import (
    QObject,
    QPointF,
    QRunnable,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QSlider,
)

from beheread.infra.archive import Archive, ArchiveClosedError, find_next_volume
from beheread.infra.imaging import compute_content_rect
from beheread.ui.reader.imaging import average_color, darken


class PageAnalysis(NamedTuple):
    """Resultat de l'analyse d'une page, faite par PageLoader."""
    content_rect: object   # QRect de contenu (marges rognees) ou None
    ambient: object        # QColor de fond Ambilight (moyenne assombrie)


class _PageSlider(QSlider):
    """Slider dont un clic ou un glisser n'importe ou dans la barre saute
    directement a la position visee (pas de pas incremental). Emet aussi la
    page survolee (sans clic) pour afficher un apercu."""
    scrubbed = Signal(int)
    hovered = Signal(int, int)   # page visee, x (dans le slider) du curseur
    hoverLeft = Signal()

    MARKER = 5   # diametre des reperes de chapitre (pixels)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)   # recevoir les mouvements sans bouton
        # tome virtuel : premiere page de chaque chapitre (sauf le premier),
        # marquee d'un petit point sur la barre
        self.markers = []

    def set_markers(self, pages):
        self.markers = list(pages)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        span = self.maximum() - self.minimum()
        if not self.markers or span <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 170))
        d, y = self.MARKER, self.height() / 2
        for page in self.markers:
            x = (page - self.minimum()) / span * self.width()
            painter.drawEllipse(QPointF(x, y), d / 2, d / 2)
        painter.end()

    def _value_at(self, x):
        ratio = min(1.0, max(0.0, x / max(1, self.width())))
        return round(self.minimum() + ratio * (self.maximum() - self.minimum()))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            value = self._value_at(event.position().x())
            self.setValue(value)
            self.scrubbed.emit(value)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        x = int(event.position().x())
        if event.buttons() & Qt.LeftButton:
            value = self._value_at(x)
            self.setValue(value)
            self.scrubbed.emit(value)
            event.accept()
            return
        self.hovered.emit(self._value_at(x), x)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hoverLeft.emit()
        super().leaveEvent(event)


class _PageSignals(QObject):
    # index, image (nulle si illisible), analyse (recadrage, couleur Ambilight)
    # ou None si non demandee
    loaded = Signal(int, QImage, object)


class PageLoader(QRunnable):
    """Decode une page hors du thread UI. `analyze` : calcule aussi, dans ce
    thread, le rectangle de contenu (recadrage des marges) et la couleur
    moyenne (Ambilight), trop couteux pour paintEvent. `max_height` : decodage
    directement reduit (apercu au survol de la barre)."""

    def __init__(self, archive: Archive, index: int, analyze=False, max_height=0):
        super().__init__()
        self.archive = archive
        self.index = index
        self.analyze = analyze
        self.max_height = max_height
        self.signals = _PageSignals()

    def run(self):
        try:
            img = self.archive.read_image(self.index, max_height=self.max_height)
        except ArchiveClosedError:
            return   # lecteur ferme entre-temps : plus personne n'attend cette page
        except Exception:
            logging.warning("Page %d illisible dans %s",
                            self.index, self.archive.path, exc_info=True)
            img = QImage()
        analysis = None
        if self.analyze and not img.isNull():
            try:
                analysis = PageAnalysis(compute_content_rect(img), darken(average_color(img)))
            except Exception:
                logging.warning("Analyse de la page %d impossible dans %s",
                                self.index, self.archive.path, exc_info=True)
        self.signals.loaded.emit(self.index, img, analysis)


class _NextVolumeSignals(QObject):
    found = Signal(object)   # chemin du tome suivant, ou None


class NextVolumeProbe(QRunnable):
    """Cherche le tome suivant (scan du dossier, potentiellement lent sur
    disque reseau) et « chauffe » son archive - ouverture + lecture de la
    premiere page - en arriere-plan, des que la lecture approche de la fin.
    L'enchainement (touche Entree / fiche de fin) devient ainsi instantane :
    ni scan ni premier acces disque a payer au moment ou l'utilisateur agit."""

    def __init__(self, path: str, known=None):
        super().__init__()
        self.path = path
        self.known = known   # suivant deja donne par la bibliotheque : seulement a prechauffer
        self.signals = _NextVolumeSignals()

    def run(self):
        try:
            nxt = self.known or find_next_volume(self.path)
        except Exception:
            logging.warning("Recherche du tome suivant a %s en echec",
                            self.path, exc_info=True)
            nxt = None
        if nxt:
            try:   # amorce le cache disque de l'OS (open + read + close)
                ar = Archive(nxt)
                ar.read_image(0, max_height=200)
                ar.close()
            except Exception:
                logging.warning("Prechauffage impossible du tome suivant %s", nxt, exc_info=True)
        self.signals.found.emit(nxt)
