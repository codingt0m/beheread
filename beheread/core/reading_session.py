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
* le rythme : secondes PAR PAGE, sur les dernieres vues lues en avancant -
  le temps total de ces vues divise par leur nombre de pages (une double
  page ne compte pas double). Une moyenne et non une mediane : le temps
  passe sur une page est tres asymetrique (pages d'action vite lues, pages
  de dialogue bien plus longues) et la mediane sous-estimait nettement le
  temps reel, de moitie environ.
"""

from collections import deque

MIN_DWELL = 1.0     # secondes d'affichage en dessous desquelles une vue n'est pas lue
PAUSE_CAP = 90.0    # secondes : au-dela, on considere une pause (temps ignore)
PACE_WINDOW = 60    # vues recentes retenues pour le rythme


class SessionMeter:
    def __init__(self, now: float, min_dwell: float = MIN_DWELL, pause_cap: float = PAUSE_CAP):
        self.min_dwell = min_dwell
        self.pause_cap = pause_cap
        self.active_seconds = 0.0
        self.pages: set[int] = set()              # indices des pages lues
        # (secondes, pages) des vues lues en avancant
        self.samples: deque[tuple[float, int]] = deque(maxlen=PACE_WINDOW)
        self._since: float | None = now           # debut d'affichage de la vue (None : a l'arret)

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
                self.samples.append((dwell, len(shown)))

    def pace(self, min_samples: int = 1):
        """Rythme de la seance (secondes par page), ou None tant qu'il n'y a
        pas assez de vues lues pour l'estimer."""
        if len(self.samples) < max(1, min_samples):
            return None
        return sum(s for s, _ in self.samples) / sum(n for _, n in self.samples)
