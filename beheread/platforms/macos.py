"""Implementation macOS de beheread.platforms (voir __init__.py)."""

import logging
import os
import shutil
import subprocess
from pathlib import Path

NAME = "macos"

# ------------------------------------------------------------------ donnees


def data_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "Beheread"


# Fichier iCloud Drive "sans donnees" (option « Optimiser le stockage du
# Mac ») : seul l'espace reserve est sur le disque, la moindre lecture
# declencherait un telechargement complet et bloquant. Le drapeau est lu par
# os.stat, sans ouvrir le fichier.
_SF_DATALESS = 0x40000000


def is_cloud_placeholder(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_flags", 0) & _SF_DATALESS)


# ------------------------------------------------------------------ secrets
# Le secret est range dans le Trousseau de l'utilisateur (service
# "Beheread") ; settings.json ne garde que la reference "keychain:<nom>".
# Une copie de settings.json sur un autre Mac ou un autre compte ne donne donc
# pas acces au secret. Le moteur macOS de `keyring` est appele directement
# (sans la detection de moteur par points d'entree, fragile une fois
# l'application emballee).

_SERVICE = "Beheread"
_PREFIX_KEYCHAIN = "keychain:"


def _keychain():
    from keyring.backends import macOS
    return macOS.Keyring()


def protect_secret(name: str, secret: str) -> str:
    _keychain().set_password(_SERVICE, name, secret)
    return _PREFIX_KEYCHAIN + name


def unprotect_secret(value: str):
    if not value.startswith(_PREFIX_KEYCHAIN):
        return None
    return _keychain().get_password(_SERVICE, value[len(_PREFIX_KEYCHAIN):])


def discard_secret(value: str):
    if not value.startswith(_PREFIX_KEYCHAIN):
        return
    from keyring.errors import PasswordDeleteError
    try:
        _keychain().delete_password(_SERVICE, value[len(_PREFIX_KEYCHAIN):])
    except PasswordDeleteError:
        pass   # deja absent du Trousseau


# ------------------------------------------------------------------ demarrage


def before_app_start():
    pass


def allow_foreground():
    """Rien a faire : macOS active l'application que l'on ouvre (et lui
    transmet les fichiers du Finder), sans autorisation a ceder."""


def hide_window(win):
    """Masque toute l'application, comme ⌘H : une fenetre en plein ecran ne
    peut pas etre reduite dans le Dock. Un clic sur l'icone du Dock la
    rappelle, toujours en plein ecran. Repli : reduire la fenetre."""
    try:
        _ns_app_hide()
    except Exception:
        logging.warning("Masquage de l'application impossible", exc_info=True)
        win.showMinimized()


def _ns_app_hide():
    """[[NSApplication sharedApplication] hide:nil], par le runtime
    Objective-C (objc_msgSend appele avec son prototype exact, obligatoire
    sur Apple Silicon)."""
    import ctypes
    import ctypes.util
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send = ctypes.cast(objc.objc_msgSend, ctypes.CFUNCTYPE(
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p))
    send_obj = ctypes.cast(objc.objc_msgSend, ctypes.CFUNCTYPE(
        None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p))
    ns_app = send(objc.objc_getClass(b"NSApplication"),
                  objc.sel_registerName(b"sharedApplication"))
    send_obj(ns_app, objc.sel_registerName(b"hide:"), None)


# ------------------------------------------------------------------ fichiers


def reveal_in_file_manager(path: str):
    """`open -R` ouvre le dossier dans le Finder, fichier selectionne."""
    try:
        subprocess.Popen(["open", "-R", path])
    except OSError:
        logging.warning("Ouverture du Finder impossible", exc_info=True)


def _move_to_trash(path: str):
    """Corbeille du Finder, par Qt (NSFileManager) : sans PyObjC, dont
    send2trash a besoin sous macOS."""
    from PySide6.QtCore import QFile
    result = QFile.moveToTrash(path)
    ok = result[0] if isinstance(result, tuple) else result
    if not ok:
        raise OSError(f"impossible de mettre « {path} » à la Corbeille")


def trash_function():
    return _move_to_trash


TRASH_NAME = "la Corbeille"


# Une application lancee depuis le Finder n'herite pas du PATH du terminal :
# les outils installes par Homebrew sont donc cherches a leurs emplacements
# standard (Apple Silicon, puis Intel).
_BREW_BIN = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))


def _found(names, dirs=_BREW_BIN):
    paths = [d / n for d in dirs for n in names]
    for n in names:
        which = shutil.which(n)
        if which:
            paths.append(Path(which))
    return paths


def rar_tools(app_dir: Path) -> dict:
    """unrar (depose a cote de l'application ou installe), puis 7-Zip ; a
    defaut, bsdtar, fourni avec macOS, ouvre la plupart des RAR sans rien
    installer."""
    return {"unrar": [app_dir / "unrar", *_found(["unrar"])],
            "sevenzip": _found(["7zz", "7z"]),
            "bsdtar": [Path("/usr/bin/bsdtar")]}


RAR_HELP = ("Installez 7-Zip ou RAR avec Homebrew : brew install sevenzip "
            "(ou brew install --cask rar).")


# ------------------------------------------------------------------ raccourci global
# Pas de touche boss globale sous macOS (non retenue pour le portage) ; la
# touche C du lecteur reste disponible.

GLOBAL_HOTKEY = False
GlobalHotkey = None
