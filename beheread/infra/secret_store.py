"""Protection locale des secrets (jeton AniList).

Le secret n'est jamais ecrit en clair dans settings.json : la protection
native du systeme s'en charge (voir beheread.platforms) :

* Windows : DPAPI, liee a la session de l'utilisateur ;
* macOS : le Trousseau de l'utilisateur ; settings.json ne garde qu'une
  reference.

Une copie de settings.json sur un autre compte ou un autre appareil ne permet
pas de relire le secret. Sur les autres systemes (non pris en charge), repli
sur un simple encodage, signale dans le journal.
"""

import base64
import logging

from beheread import platforms

_PREFIX_PLAIN = "plain:"


def protect(secret: str, name: str = "anilist") -> str:
    return platforms.protect_secret(name, secret)


def unprotect(value: str):
    """Secret dechiffre, ou None si absent/illisible (autre compte, fichier
    copie depuis un autre appareil, valeur corrompue)."""
    if not value:
        return None
    try:
        if value.startswith(_PREFIX_PLAIN):
            return base64.b64decode(value[len(_PREFIX_PLAIN):]).decode("utf-8")
        return platforms.unprotect_secret(value)
    except Exception:
        logging.warning("Secret illisible (compte ou appareil different ?)")
    return None


def discard(value: str):
    """Oublie le secret reference par `value` (deconnexion)."""
    if not value:
        return
    try:
        platforms.discard_secret(value)
    except Exception:
        logging.warning("Effacement du secret en echec", exc_info=True)
