"""Implementation de repli de beheread.platforms (Linux et autres systemes,
non pris en charge officiellement) : rien de natif, des equivalents simples
qui laissent l'application utilisable. Voir __init__.py."""

import logging
import os
import shutil
from pathlib import Path

NAME = "generic"

# ------------------------------------------------------------------ donnees


def data_dir() -> Path:
    return Path.home() / ".manga-reader-py"


def is_cloud_placeholder(st: os.stat_result) -> bool:
    return False


# ------------------------------------------------------------------ secrets
# Aucun coffre systeme utilise : le secret est seulement encode (le prefixe
# "plain:" est relu par secret_store sur toutes les plateformes).

def protect_secret(name: str, secret: str) -> str:
    import base64
    logging.warning("Coffre de secrets indisponible sur ce systeme : secret seulement encode")
    return "plain:" + base64.b64encode(secret.encode("utf-8")).decode("ascii")


def unprotect_secret(value: str):
    return None


def discard_secret(value: str):
    pass


# ------------------------------------------------------------------ demarrage


def before_app_start():
    pass


def allow_foreground():
    pass


def hide_window(win):
    """Reduit la fenetre : elle reste dans la barre des taches."""
    win.showMinimized()


# ------------------------------------------------------------------ fichiers


REVEAL_LABEL = "Ouvrir le dossier"


def reveal_in_file_manager(path: str):
    """Ouvre le dossier du fichier (sans pouvoir le selectionner)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))


def trash_function():
    """send2trash (corbeille du systeme), ou None s'il est absent."""
    try:
        from send2trash import send2trash
    except Exception:
        return None
    return send2trash


TRASH_NAME = "la corbeille"


def rar_tools(app_dir: Path) -> dict:
    """UnRAR depose a cote de l'application, sinon les outils du PATH que
    rarfile cherche de lui-meme (unrar, unar, 7z, bsdtar)."""
    unrar = [app_dir / "unrar"]
    found = shutil.which("unrar")
    if found:
        unrar.append(Path(found))
    return {"unrar": unrar, "sevenzip": [], "bsdtar": []}


RAR_HELP = "Installez unrar (ou 7-Zip) avec le gestionnaire de paquets du système."


# ------------------------------------------------------------------ raccourci global

GLOBAL_HOTKEY = False
GlobalHotkey = None
