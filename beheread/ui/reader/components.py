"""Composants du lecteur : barre de pages cliquable, chargement de page en
arriere-plan, recherche et prechauffage du tome suivant."""

import logging

from PySide6.QtCore import (
    QObject,
    QRunnable,
    Qt,
    Signal,
)
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QSlider,
)

from beheread.infra.archive import Archive, ArchiveClosedError, find_next_volume


class _PageSlider(QSlider):
    """Slider dont un clic ou un glisser n'importe ou dans la barre saute
    directement a la position visee (pas de pas incremental). Emet aussi la
    page survolee (sans clic) pour afficher un apercu."""
    scrubbed = Signal(int)
    hovered = Signal(int, int)   # page visee, x (dans le slider) du curseur
    hoverLeft = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)   # recevoir les mouvements sans bouton

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
    loaded = Signal(int, QImage)


class PageLoader(QRunnable):
    def __init__(self, archive: Archive, index: int):
        super().__init__()
        self.archive = archive
        self.index = index
        self.signals = _PageSignals()

    def run(self):
        try:
            img = self.archive.read_image(self.index)
        except ArchiveClosedError:
            return   # lecteur ferme entre-temps : plus personne n'attend cette page
        except Exception:
            logging.warning("Page %d illisible dans %s",
                            self.index, self.archive.path, exc_info=True)
            img = QImage()
        self.signals.loaded.emit(self.index, img)


class _NextVolumeSignals(QObject):
    found = Signal(object)   # chemin du tome suivant, ou None


class NextVolumeProbe(QRunnable):
    """Cherche le tome suivant (scan du dossier, potentiellement lent sur
    disque reseau) et « chauffe » son archive - ouverture + lecture de la
    premiere page - en arriere-plan, des que la lecture approche de la fin.
    L'enchainement (touche Entree / fiche de fin) devient ainsi instantane :
    ni scan ni premier acces disque a payer au moment ou l'utilisateur agit."""

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.signals = _NextVolumeSignals()

    def run(self):
        try:
            nxt = find_next_volume(self.path)
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
