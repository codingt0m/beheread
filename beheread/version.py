"""Numero de version de Beheread (SemVer : MAJOR.MINOR.PATCH).

Source unique du numero : build.bat le lit pour nommer l'installateur et
l'archive, et la publication (.github/workflows/release.yml) refuse un tag
vX.Y.Z qui ne lui correspond pas. A incrementer manuellement, avec une
entree dans CHANGELOG.md. Affiche dans l'info-bulle du logo (voir
ui/library/chrome.py) et consigne en tete du journal au demarrage (voir
applogging.py) - utile pour savoir quel build tourne quand on compare un
comportement entre deux versions installees."""

__version__ = "1.1.0"
