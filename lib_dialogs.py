"""Boites de dialogue de la bibliotheque : gestion des dossiers sources
(panneau facon Plex)."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

import icons
import theme
from lib_workers import _FolderCountWorker


class FolderManagerDialog(QDialog):
    """Panneau facon Plex : liste des dossiers sources avec leur nombre de
    mangas, ajout par navigation et retrait individuel. Rien n'est ecrit tant
    que l'utilisateur ne valide pas (bouton « Enregistrer »)."""

    def __init__(self, folders, colors, parent=None):
        super().__init__(parent)
        self.c = colors
        self._folders = list(folders)      # copie de travail
        self._rows = {}                    # dossier -> (widget ligne, label compte)
        self._pool = QThreadPool.globalInstance()

        self.setWindowTitle("Dossiers de la bibliothèque")
        self.setMinimumWidth(560)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)

        title = QLabel("Ajouter des dossiers à votre bibliothèque")
        title.setObjectName("fmTitle")
        root.addWidget(title)

        # zone defilante contenant une ligne par dossier
        self._scroll = QScrollArea()
        self._scroll.setObjectName("fmScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list_host)
        root.addWidget(self._scroll, 1)

        # bouton d'ajout par navigation
        self.btn_browse = QPushButton("  Parcourir et choisir un dossier")
        self.btn_browse.setObjectName("fmBrowse")
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        self.btn_browse.setIcon(icons.folder_plus(self.c["text"]))
        self.btn_browse.clicked.connect(self._browse)
        browse_row = QHBoxLayout()
        browse_row.addStretch(1)
        browse_row.addWidget(self.btn_browse)
        browse_row.addStretch(1)
        root.addLayout(browse_row)

        self._empty = QLabel("Aucun dossier source. Ajoutez-en un pour "
                             "constituer votre bibliothèque.")
        self._empty.setObjectName("fmEmpty")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setWordWrap(True)
        root.addWidget(self._empty)

        # boutons de validation
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_cancel = QPushButton("Annuler")
        self.btn_cancel.setObjectName("fmCancel")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("Enregistrer les modifications")
        self.btn_save.setObjectName("fmSave")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.accept)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_save)
        root.addLayout(buttons)

        self._apply_style()
        for f in self._folders:
            self._add_row(f)
        self._update_empty()

    # ----- API -----
    def result_folders(self):
        return list(self._folders)

    # ----- construction des lignes -----
    def _add_row(self, folder):
        row = QFrame()
        row.setObjectName("fmRow")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(14, 8, 10, 8)
        rl.setSpacing(10)

        path_lbl = QLabel(folder)
        path_lbl.setObjectName("fmPath")
        path_lbl.setToolTip(folder)
        path_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        rl.addWidget(path_lbl, 1)

        count_lbl = QLabel("…")
        count_lbl.setObjectName("fmCount")
        count_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rl.addWidget(count_lbl)

        btn_x = QToolButton()
        btn_x.setObjectName("fmRemove")
        btn_x.setCursor(Qt.PointingHandCursor)
        btn_x.setToolTip("Retirer ce dossier")
        btn_x.setIcon(icons.x_mark(self.c["text_dim"]))
        btn_x.setIconSize(QSize(14, 14))
        btn_x.setFixedSize(26, 26)
        btn_x.clicked.connect(lambda: self._remove_row(folder))
        rl.addWidget(btn_x)

        # insere avant l'etirement final
        self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        self._rows[folder] = (row, count_lbl)

        # comptage asynchrone des mangas
        worker = _FolderCountWorker(folder)
        worker.signals.done.connect(self._on_count)
        self._pool.start(worker)

    def _on_count(self, folder, n):
        entry = self._rows.get(folder)
        if not entry:
            return
        _, count_lbl = entry
        if n < 0:
            count_lbl.setText("dossier introuvable")
        elif n == 0:
            count_lbl.setText("aucun manga")
        else:
            count_lbl.setText(f"{n} manga" + ("s" if n > 1 else ""))

    def _remove_row(self, folder):
        entry = self._rows.pop(folder, None)
        if entry:
            entry[0].setParent(None)
            entry[0].deleteLater()
        if folder in self._folders:
            self._folders.remove(folder)
        self._update_empty()

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier de mangas")
        if not folder:
            return
        folder = str(Path(folder))
        if folder in self._folders:
            QMessageBox.information(self, "Déjà présent",
                                    "Ce dossier est déjà dans la bibliothèque.")
            return
        self._folders.append(folder)
        self._add_row(folder)
        self._update_empty()

    def _update_empty(self):
        has = bool(self._folders)
        self._empty.setVisible(not has)
        self._scroll.setVisible(has)

    def _apply_style(self):
        c = self.c
        self.setStyleSheet(f"""
            QDialog {{ background: {c['window']}; }}
            QLabel#fmTitle {{
                color: {c['text']};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#fmEmpty {{ color: {c['text_dim']}; font-size: 13px; padding: 20px; }}
            QScrollArea#fmScroll {{ border: none; background: transparent; }}
            QFrame#fmRow {{
                background: {c['button']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
            QLabel#fmPath {{ color: {c['text']}; font-size: 13px; }}
            QLabel#fmCount {{ color: {c['text_dim']}; font-size: 12px; padding-right: 4px; }}
            QToolButton#fmRemove {{
                background: transparent;
                border: none;
                border-radius: 13px;
            }}
            QToolButton#fmRemove:hover {{ background: {theme.ACCENT_DIM}; }}
            QPushButton#fmBrowse {{
                color: {c['text']};
                background: {c['button']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton#fmBrowse:hover {{ background: {c['button_hover']}; }}
            QPushButton#fmCancel {{
                color: {c['text']};
                background: {c['button']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                padding: 8px 18px;
                font-size: 13px;
            }}
            QPushButton#fmCancel:hover {{ background: {c['button_hover']}; }}
            QPushButton#fmSave {{
                color: white;
                background: {theme.ACCENT};
                border: none;
                border-radius: 8px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton#fmSave:hover {{ background: #d14433; }}
        """)
