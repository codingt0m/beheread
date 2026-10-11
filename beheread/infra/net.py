"""Acces reseau commun aux clients d'API (Google Books, AniList, MangaDex,
BnF) : espacement des requetes par service, pause demandee par le service
apres un refus pour exces de requetes (HTTP 429), User-Agent.

Chaque client garde ses particularites (format, erreurs, repli DNS de la
BnF) ; seul ce qui etait recopie a l'identique dans chacun est ici."""

import threading
import time

from beheread.version import __version__

# identifiant applicatif : attendu par MangaDex (qui refuse un User-Agent de
# navigateur) et par courtoisie envers la BnF
APP_USER_AGENT = f"Beheread/{__version__} (+https://github.com/codingt0m/beheread)"
# User-Agent de navigateur : AniList est protege par Cloudflare, qui bloque
# les requetes dont le User-Agent ressemble a un script (voir anilist.py)
BROWSER_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

# pause apres un 429 sans en-tete Retry-After exploitable, et plafond (un
# en-tete aberrant ne doit pas suspendre les recherches pendant des heures)
DEFAULT_BACK_OFF = 60.0
MAX_BACK_OFF = 300.0


class RateLimiter:
    """Espace les requetes vers un service d'au moins `min_interval`
    secondes. Plusieurs pools de threads (metadonnees par tome et par serie,
    suivi AniList) interrogent le meme service en parallele : chaque appel a
    wait() reserve le creneau suivant sous verrou, puis attend hors verrou."""

    def __init__(self, min_interval: float, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = min_interval
        self._clock, self._sleep = clock, sleep   # remplaces dans les tests
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = self._clock()
            start = max(now, self._next)
            self._next = start + self.min_interval
        if start > now:
            self._sleep(start - now)

    def back_off(self, seconds: float):
        """Le service a demande une pause : aucune requete avant `seconds`."""
        with self._lock:
            self._next = max(self._next, self._clock() + seconds)


def retry_after(error) -> float:
    """Pause demandee par une reponse 429 (en-tete Retry-After en secondes),
    bornee ; DEFAULT_BACK_OFF si l'en-tete manque ou n'est pas un nombre."""
    try:
        value = float((getattr(error, "headers", None) or {}).get("Retry-After", ""))
    except (TypeError, ValueError):
        return DEFAULT_BACK_OFF
    return min(MAX_BACK_OFF, max(1.0, value))
