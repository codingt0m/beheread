"""Implementation Windows de beheread.platforms (voir __init__.py)."""

import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter

NAME = "windows"

# ------------------------------------------------------------------ donnees


def data_dir() -> Path:
    base = os.environ.get("APPDATA", str(Path.home()))
    return Path(base) / "MangaReaderPy"


# Attributs des fichiers "cloud" (iCloud Drive, OneDrive) dont le contenu
# n'est PAS present sur le disque : le fichier n'est qu'un espace reserve, et
# la moindre lecture (meme 1 octet) declenche son telechargement complet et
# bloquant par le fournisseur cloud. On doit donc les detecter AVANT toute
# ouverture (os.stat suffit et ne declenche rien).
_FILE_ATTRIBUTE_OFFLINE = 0x00001000
_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
_CLOUD_PLACEHOLDER_ATTRS = (_FILE_ATTRIBUTE_OFFLINE
                            | _FILE_ATTRIBUTE_RECALL_ON_OPEN
                            | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)


def is_cloud_placeholder(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & _CLOUD_PLACEHOLDER_ATTRS)


# ------------------------------------------------------------------ secrets
# DPAPI (CryptProtectData), la protection native du systeme, liee a la session
# de l'utilisateur : une copie de settings.json sur un autre compte ou un autre
# PC ne permet pas de relire le secret.

_PREFIX_DPAPI = "dpapi:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), "Beheread" if protect else None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise OSError(ctypes.GetLastError(), "DPAPI en echec")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def protect_secret(name: str, secret: str) -> str:
    import base64
    return _PREFIX_DPAPI + base64.b64encode(_dpapi(secret.encode("utf-8"), True)).decode("ascii")


def unprotect_secret(value: str):
    if not value.startswith(_PREFIX_DPAPI):
        return None
    import base64
    return _dpapi(base64.b64decode(value[len(_PREFIX_DPAPI):]), False).decode("utf-8")


def discard_secret(value: str):
    """Rien a effacer : le secret chiffre vit seulement dans settings.json."""


# ------------------------------------------------------------------ demarrage


def before_app_start():
    """Sans ceci, Windows regroupe la fenetre sous l'icone de python.exe/
    pythonw.exe dans la barre des taches (il identifie l'appli par le nom de
    l'executable, pas par setWindowIcon). Lui donner un identifiant propre
    force Windows a utiliser l'icone de la fenetre a la place."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Beheread.MangaReader.1")
    except Exception:
        logging.warning("Echec SetCurrentProcessExplicitAppUserModelID", exc_info=True)


def allow_foreground():
    """Windows n'autorise un processus a passer au premier plan que si le
    processus actif le lui permet. L'instance secondaire (celle que
    l'utilisateur vient de lancer) cede donc ce droit a l'instance principale,
    sans quoi celle-ci ne ferait que clignoter dans la barre des taches."""
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(0xFFFFFFFF)   # ASFW_ANY
    except Exception:
        logging.debug("AllowSetForegroundWindow en echec", exc_info=True)


def hide_window(win):
    """Reduit la fenetre : elle reste dans la barre des taches."""
    win.showMinimized()


# ------------------------------------------------------------------ fichiers


REVEAL_LABEL = "Afficher dans l'explorateur"


def reveal_in_file_manager(path: str):
    """"explorer /select," met le fichier en surbrillance dans son dossier."""
    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


def trash_function():
    """send2trash (corbeille du systeme), ou None s'il est absent."""
    try:
        from send2trash import send2trash
    except Exception:
        return None
    return send2trash


TRASH_NAME = "la corbeille de Windows"


def rar_tools(app_dir: Path) -> dict:
    """Outils de decompression RAR candidats, par ordre de preference
    (voir archive._init_rarfile) : UnRAR.exe depose a cote de Beheread ou
    installe avec WinRAR, puis 7-Zip a son emplacement standard (sans avoir a
    ajouter son dossier au PATH)."""
    unrar = [app_dir / "unrar.exe", app_dir / "UnRAR.exe"]
    sevenzip = []
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            unrar.append(Path(base) / "WinRAR" / "UnRAR.exe")
            sevenzip.append(Path(base) / "7-Zip" / "7z.exe")
    return {"unrar": unrar, "sevenzip": sevenzip, "bsdtar": []}


RAR_HELP = ("Installez WinRAR ou 7-Zip, ou placez UnRAR.exe dans le "
            "dossier de Beheread.")


# ------------------------------------------------------------------ raccourci global
# Touche "boss" : une fenetre reduite/masquee ne recoit plus les evenements
# clavier de Qt ; pour la rappeler d'une seule combinaison depuis n'importe
# ou, il faut passer par l'API Windows RegisterHotKey. Le message WM_HOTKEY
# arrive dans la file du thread principal, ou Qt le fait transiter par les
# filtres d'evenements natifs installes sur l'application.

GLOBAL_HOTKEY = True

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000  # evite les repetitions tant que la touche est maintenue

VK_C = 0x43


class GlobalHotkey(QAbstractNativeEventFilter):
    """Enregistre un raccourci global et appelle `callback` quand il est
    presse. A installer via `app.installNativeEventFilter(instance)` et a
    garder en reference (sinon Python le collecte et le filtre disparait)."""

    def __init__(self, callback, hotkey_id=1, mods=MOD_CONTROL | MOD_ALT, vk=VK_C):
        super().__init__()
        self._callback = callback
        self._id = hotkey_id
        self._registered = False
        import ctypes
        from ctypes import wintypes
        self._user32 = ctypes.windll.user32
        self._user32.RegisterHotKey.argtypes = [
            wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL
        try:
            self._registered = bool(self._user32.RegisterHotKey(
                None, self._id, mods | MOD_NOREPEAT, vk))
        except Exception:
            self._registered = False
        if not self._registered:
            # cause frequente : une autre appli a deja reserve cette
            # combinaison au niveau de Windows (RegisterHotKey est exclusif).
            logging.warning(
                "Raccourci global (touche boss) non enregistre - deja pris "
                "par une autre application ?")

    def nativeEventFilter(self, event_type, message):
        if self._registered:
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._id:
                self._callback()
        return False, 0

    def unregister(self):
        if self._registered:
            try:
                self._user32.UnregisterHotKey(None, self._id)
            except Exception:
                logging.debug("Desenregistrement du raccourci global en echec", exc_info=True)
            self._registered = False
