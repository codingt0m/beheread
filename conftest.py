"""Presence de ce fichier a la racine : pytest ajoute ce dossier au sys.path,
de sorte que les tests puissent importer le package `beheread` sans
installation.

Les tests qui ont besoin de Qt utilisent les fixtures de pytest-qt (`qapp`,
`qtbot`), avec la plateforme « offscreen » : aucune fenetre ne s'affiche."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _default_accent():
    """La couleur d'accentuation est un etat global (theme.py) : chaque test
    repart de la couleur d'origine, meme apres un test qui l'a changee."""
    yield
    from beheread.ui import theme
    theme.set_accent(None)
