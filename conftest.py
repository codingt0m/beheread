"""Presence de ce fichier a la racine : pytest ajoute ce dossier au sys.path,
de sorte que les tests puissent importer le package `beheread` sans
installation.

Les tests qui ont besoin de Qt utilisent les fixtures de pytest-qt (`qapp`,
`qtbot`), avec la plateforme « offscreen » : aucune fenetre ne s'affiche."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
