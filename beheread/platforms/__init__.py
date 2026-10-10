"""Tout ce qui depend du systeme d'exploitation, derriere une seule interface.

Le reste de l'application n'interroge jamais `sys.platform` : il appelle les
noms ci-dessous, fournis par l'implementation du systeme courant :

* windows.py : Windows 10/11 (DPAPI, RegisterHotKey, Explorateur...) ;
* macos.py   : macOS (Trousseau, Finder...) ;
* generic.py : repli pour les autres systemes (non pris en charge).

Chaque implementation expose exactement les noms de API (verifie par
tests/test_platforms.py).
"""

import sys

if sys.platform == "win32":
    from beheread.platforms import windows as _impl
elif sys.platform == "darwin":
    from beheread.platforms import macos as _impl
else:
    from beheread.platforms import generic as _impl

API = (
    "NAME",                    # "windows", "macos" ou "generic"
    "data_dir",                # () -> Path : dossier des donnees de l'utilisateur
    "is_cloud_placeholder",    # (os.stat_result) -> bool : fichier cloud non telecharge
    "protect_secret",          # (nom, secret) -> str : valeur a enregistrer dans settings
    "unprotect_secret",        # (valeur) -> str | None
    "discard_secret",          # (valeur) : oublie le secret (deconnexion)
    "before_app_start",        # () : reglages a faire avant de creer QApplication
    "allow_foreground",        # () : instance secondaire -> premier plan a l'instance principale
    "hide_window",             # (fenetre) : la masquer instantanement (touche C du lecteur)
    "reveal_in_file_manager",  # (chemin) : montre le fichier dans l'explorateur / le Finder
    "rar_tools",               # (dossier de l'app) -> {"unrar"|"sevenzip"|"bsdtar": [Path]}
    "RAR_HELP",                # texte : comment obtenir un outil RAR
    "GLOBAL_HOTKEY",           # bool : raccourci global (touche boss) disponible
    "GlobalHotkey",            # classe du raccourci global, ou None
)

NAME = _impl.NAME
IS_WINDOWS = NAME == "windows"
IS_MACOS = NAME == "macos"
data_dir = _impl.data_dir
is_cloud_placeholder = _impl.is_cloud_placeholder
protect_secret = _impl.protect_secret
unprotect_secret = _impl.unprotect_secret
discard_secret = _impl.discard_secret
before_app_start = _impl.before_app_start
allow_foreground = _impl.allow_foreground
hide_window = _impl.hide_window
reveal_in_file_manager = _impl.reveal_in_file_manager
rar_tools = _impl.rar_tools
RAR_HELP = _impl.RAR_HELP
GLOBAL_HOTKEY = _impl.GLOBAL_HOTKEY
GlobalHotkey = _impl.GlobalHotkey
