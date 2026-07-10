"""Journalisation fichier de l'application.

Jusqu'ici, les echecs des taches d'arriere-plan (scan reseau, ecriture disque,
archive corrompue...) etaient avales silencieusement (`except Exception:
pass`) : rien n'indiquait qu'un probleme s'etait produit ni pourquoi. Ce
module ouvre un fichier `beheread.log` (avec rotation) dans le meme dossier
que les autres donnees de l'application, pour qu'un comportement anormal
signale par un utilisateur puisse etre diagnostique apres coup.

A appeler une seule fois, en tout debut de main(), avant toute autre
operation susceptible d'echouer."""

import logging
from logging.handlers import RotatingFileHandler

from storage import data_dir
from version import __version__

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_MAX_BYTES = 1_000_000
_BACKUPS = 2


def setup():
    root = logging.getLogger()
    if root.handlers:
        return   # deja configure (ex. si main() est appele plusieurs fois)
    root.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        data_dir() / "beheread.log", maxBytes=_MAX_BYTES,
        backupCount=_BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root.addHandler(handler)
    logging.info("=== Beheread v%s demarre ===", __version__)
