"""Suivi de lecture sur un site externe : interface commune des services de
suivi (AniList, voir anilist_tracker.py) et diffusion des evenements de
lecture a tous les services actifs.

L'application ne connait que cette interface pour ce qui se passe pendant la
lecture (tome termine, fin de seance) : brancher un autre service revient a
l'ajouter a TrackerSet. Les ecrans propres a un service (connexion,
association d'une serie) restent les siens.
"""

from PySide6.QtCore import QObject, Signal


class Tracker(QObject):
    """Service de suivi de lecture. Chaque methode est appelee sur le thread
    UI ; les envois reseau se font dans les threads du service."""

    statusChanged = Signal(str)    # message d'etat a afficher (preferences)
    seriesUpdated = Signal(str)    # cle de serie dont l'etat de suivi a change

    NAME = ""   # nom affiche du service

    def connected(self) -> bool:
        """Un compte est-il associe ?"""
        raise NotImplementedError

    def enabled(self) -> bool:
        """Connecte, et le suivi automatique est-il active ?"""
        raise NotImplementedError

    def on_volumes_finished(self, paths):
        """Tomes termines (lecteur, ou « marquer comme lu »)."""
        raise NotImplementedError

    def on_session_end(self, path):
        """Fin d'une seance de lecture de ce tome."""
        raise NotImplementedError

    def flush_pending(self):
        """Envoie ce qui attend encore (au demarrage, apres un echec)."""
        raise NotImplementedError


class TrackerSet:
    """Diffuse les evenements de lecture a chaque service de suivi."""

    def __init__(self, trackers=()):
        self.trackers = list(trackers)

    def __iter__(self):
        return iter(self.trackers)

    def on_volumes_finished(self, paths):
        for tracker in self.trackers:
            tracker.on_volumes_finished(paths)

    def on_session_end(self, path):
        for tracker in self.trackers:
            tracker.on_session_end(path)

    def flush_pending(self):
        for tracker in self.trackers:
            tracker.flush_pending()
