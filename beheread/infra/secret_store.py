"""Chiffrement local des secrets (jeton AniList).

Sous Windows : DPAPI (CryptProtectData), la protection native du systeme, liee
a la session de l'utilisateur. Le secret n'est jamais ecrit en clair dans
settings.json, et une copie de ce fichier sur un autre compte ou un autre PC
ne permet pas de le relire. Hors Windows (non pris en charge officiellement),
repli sur un simple encodage, signale dans le journal.
"""

import base64
import logging
import sys

_PREFIX_DPAPI = "dpapi:"
_PREFIX_PLAIN = "plain:"
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


def protect(secret: str) -> str:
    raw = secret.encode("utf-8")
    if sys.platform == "win32":
        return _PREFIX_DPAPI + base64.b64encode(_dpapi(raw, True)).decode("ascii")
    logging.warning("Chiffrement DPAPI indisponible hors Windows : secret seulement encode")
    return _PREFIX_PLAIN + base64.b64encode(raw).decode("ascii")


def unprotect(value: str):
    """Secret dechiffre, ou None si absent/illisible (autre compte, fichier
    copie depuis un autre PC, valeur corrompue)."""
    if not value:
        return None
    try:
        if value.startswith(_PREFIX_DPAPI) and sys.platform == "win32":
            return _dpapi(base64.b64decode(value[len(_PREFIX_DPAPI):]), False).decode("utf-8")
        if value.startswith(_PREFIX_PLAIN):
            return base64.b64decode(value[len(_PREFIX_PLAIN):]).decode("utf-8")
    except Exception:
        logging.warning("Secret illisible (compte ou appareil different ?)")
    return None
