"""Mesure d'une seance de lecture : logique pure (aucune dependance Qt,
testee isolement).

Le lecteur signale chaque changement de vue (une page, ou une paire en
double page) ; le compteur en deduit les trois mesures de la seance :

* les pages lues : celles d'une vue quittee en avancant apres y etre reste
  au moins MIN_DWELL secondes - feuilleter, maintenir une fleche ou faire
  glisser la barre de defilement ne « lit » rien ;
* le temps de lecture actif : la duree d'affichage de chaque vue lue, dans
  les deux sens (revenir relire une page, c'est lire). Au-dela de PAUSE_CAP
  secondes sur une meme vue, on considere une pause : l'intervalle est ignore ;
* le rythme : secondes PAR PAGE (la duree d'une vue divisee par son nombre
  de pages, pour qu'une double page ne compte pas double), sur les dernieres
  vues lues en avancant.
"""

import statistics
from collections import deque

MIN_DWELL = 1.0     # secondes d'affichage en dessous desquelles une vue n'est pas lue
PAUSE_CAP = 90.0    # secondes : au-dela, on considere une pause (temps ignore)
PACE_WINDOW = 60    # vues recentes retenues pour le rythme


class SessionMeter:
    def __init__(self, now: float, min_dwell: float = MIN_DWELL, pause_cap: float = PAUSE_CAP):
        self.min_dwell = min_dwell
        self.pause_cap = pause_cap
        self.active_seconds = 0.0
        self.pages = set()                        # indices des pages lues
        self.samples = deque(maxlen=PACE_WINDOW)  # secondes par page
        self._since = now                         # debut d'affichage de la vue (None : a l'arret)

    def leave(self, now: float, shown, forward: bool = True, resume: bool = True):
        """La vue affichant les pages `shown` est quittee. `forward` : en
        avancant (ou parce que le tome est fini) - seule facon de compter ses
        pages. `resume=False` arrete l'horloge (fiche de fin, fermeture) ;
        elle repart au prochain appel."""
        since, self._since = self._since, (now if resume else None)
        if since is None:
            return
        dwell = now - since
        if dwell < self.min_dwell:
            return
        timed = dwell <= self.pause_cap
        if timed:
            self.active_seconds += dwell
        if forward and shown:
            self.pages.update(shown)
            if timed:
                self.samples.append(dwell / len(shown))

    def pace(self, min_samples: int = 1):
        """Rythme median de la seance (secondes par page), ou None tant qu'il
        n'y a pas assez de vues lues pour l'estimer."""
        if len(self.samples) < max(1, min_samples):
            return None
        return statistics.median(self.samples)
