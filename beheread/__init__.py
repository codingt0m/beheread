"""Beheread - lecteur de mangas CBZ / CBR / EPUB / PDF pour Windows.

Organisation en couches :
* beheread.core     : logique pure, sans Qt ni acces disque/reseau (testee isolement) ;
* beheread.infra    : persistance, archives, clients d'API, integration Windows ;
* beheread.services : orchestration en arriere-plan (suivi AniList) ;
* beheread.ui       : interface Qt (bibliotheque, lecteur, fenetres).
Les dependances vont toujours de ui vers services, infra puis core.
"""

from beheread.version import __version__  # noqa: F401
