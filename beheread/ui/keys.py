"""Raccourcis clavier propres au systeme, et noms des touches tels qu'ils
s'affichent (aide F1, info-bulles).

Qt traduit deja les raccourcis sous macOS : « Ctrl » d'un QKeySequence ou
Qt.ControlModifier designe la touche Commande (⌘), « Meta » la touche
Controle (⌃). Seuls les TEXTES sont donc a adapter : ils sont ecrits une fois,
a la maniere de Windows (« Ctrl + F »), et `label` les traduit sous macOS
(« ⌘F »). Sous Windows, ils restent inchanges.
"""

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

from beheread import platforms

# touche ou modificateur Windows -> equivalent Mac (clavier de portable : les
# touches Pg suiv, Debut... s'obtiennent avec fn)
_MAC_NAMES = {
    "Ctrl": "⌘", "Alt": "⌥", "Maj": "⇧",
    "Suppr": "⌘⌫", "Retour arrière": "⌫", "Entrée": "↩",
    "F11": "⌃⌘F", "F5": "⌘R",
    "Pg suiv": "fn ↓", "Pg préc": "fn ↑", "Début": "fn ←", "Fin": "fn →",
}
_MAC_MODIFIERS = {"⌘", "⌥", "⇧"}
# separateur des combinaisons : « Ctrl + F » comme « Ctrl+, » (un « + » seul,
# la touche de zoom, n'est pas un separateur)
_PLUS = re.compile(r"(?<=\S)\s*\+\s*(?=\S)")


def _mac_combo(combo: str) -> str:
    parts = [_MAC_NAMES.get(p, p) for p in _PLUS.split(combo)]
    mods = "".join(p for p in parts[:-1] if p in _MAC_MODIFIERS)
    if len(mods) != len(parts) - 1:            # pas une simple combinaison
        return " + ".join(parts)
    key = parts[-1]
    # « ⌘F », « ⌘, » ; mais « ⌘ Clic », « ⌘ Molette »
    return mods + key if len(key) <= 2 else f"{mods} {key}".strip()


def label(keys: str) -> str:
    """Nom des touches pour l'utilisateur ; plusieurs touches separees par
    " / " sont traduites une a une."""
    if not platforms.IS_MACOS:
        return keys
    return " / ".join(_mac_combo(k) for k in keys.split(" / "))


def fullscreen_sequences() -> list:
    """F11, et sous macOS le raccourci standard ⌃⌘F (F11 y affiche le
    bureau, et demande fn sur un portable)."""
    seqs = [QKeySequence(Qt.Key_F11)]
    if platforms.IS_MACOS:
        seqs.append(QKeySequence("Ctrl+Meta+F"))
    return seqs


def refresh_sequences() -> list:
    """F5, et sous macOS ⌘R (F5 y demande fn)."""
    seqs = [QKeySequence(Qt.Key_F5)]
    if platforms.IS_MACOS:
        seqs.append(QKeySequence("Ctrl+R"))
    return seqs


def delete_sequences() -> list:
    """Suppr, et sous macOS ⌘⌫ (un clavier Mac n'a pas de touche Suppr)."""
    seqs = [QKeySequence(QKeySequence.Delete)]
    if platforms.IS_MACOS:
        seqs.append(QKeySequence("Ctrl+Backspace"))
    return seqs
