"""Raccourci clavier global (au niveau de Windows) pour la touche "boss".

Une fenetre reduite/masquee ne recoit plus les evenements clavier de Qt ;
pour la rappeler d'une seule combinaison depuis n'importe ou, il faut passer
par l'API Windows RegisterHotKey. Le message WM_HOTKEY arrive dans la file du
thread principal, ou Qt le fait transiter par les filtres d'evenements natifs
installes sur l'application.
"""

import logging
import sys

from PySide6.QtCore import QAbstractNativeEventFilter

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
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
        if sys.platform != "win32":
            return
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

    @property
    def registered(self):
        return self._registered

    def nativeEventFilter(self, event_type, message):
        if self._registered and sys.platform == "win32":
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
