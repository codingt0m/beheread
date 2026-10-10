"""Noms des touches affiches (ui/keys.py) : inchanges sous Windows,
traduits a la maniere du Mac sous macOS."""

import pytest

from beheread import platforms
from beheread.ui import keys


@pytest.mark.parametrize("text", ["Ctrl + F", "Ctrl+,", "F11", "Suppr", "Ctrl + Alt + C"])
def test_labels_are_unchanged_outside_macos(monkeypatch, text):
    monkeypatch.setattr(platforms, "IS_MACOS", False)
    assert keys.label(text) == text


@pytest.mark.parametrize("text, mac", [
    ("Ctrl + F", "⌘F"),
    ("Ctrl+,", "⌘,"),
    ("Ctrl + Molette", "⌘ Molette"),
    ("Ctrl + Clic / Maj + Clic", "⌘ Clic / ⇧ Clic"),
    ("F11", "⌃⌘F"),
    ("F5", "⌘R"),
    ("Suppr", "⌘⌫"),
    ("Échap / Retour arrière", "Échap / ⌫"),
    ("Pg suiv / Pg préc", "fn ↓ / fn ↑"),
    ("+ / − / 0", "+ / − / 0"),             # le « + » du zoom n'est pas un separateur
    ("Clic gauche / droit", "Clic gauche / droit"),
])
def test_labels_follow_mac_conventions(monkeypatch, text, mac):
    monkeypatch.setattr(platforms, "IS_MACOS", True)
    assert keys.label(text) == mac


def test_mac_adds_its_standard_shortcuts(monkeypatch):
    monkeypatch.setattr(platforms, "IS_MACOS", False)
    base = (len(keys.fullscreen_sequences()), len(keys.refresh_sequences()),
            len(keys.delete_sequences()))
    monkeypatch.setattr(platforms, "IS_MACOS", True)
    assert (len(keys.fullscreen_sequences()), len(keys.refresh_sequences()),
            len(keys.delete_sequences())) == tuple(n + 1 for n in base)
