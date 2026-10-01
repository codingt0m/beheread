"""Boites de dialogue de la bibliotheque : gestion des dossiers sources
(panneau facon Plex), preferences, et saisie manuelle des informations d'un
tome ou d'une serie."""

import html
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from beheread import config
from beheread.infra import anilist
from beheread.infra.anilist_auth import LocalAuthReceiver
from beheread.ui import icons, theme
from beheread.ui.help_overlay import (
    LIBRARY_SHORTCUTS,
    READER_SHORTCUTS,
    sections_css,
    sections_layout,
)
from beheread.ui.library.workers import _FolderCountWorker
from beheread.ui.reader.constants import FIT_NAMES, normalize_fit


class _ElidedPathLabel(QLabel):
    """Chemin raccourci au milieu (« … ») quand la place manque : un QLabel
    simple impose la largeur de tout son texte et poussait le bouton de
    retrait hors du dialogue."""

    def __init__(self, path):
        super().__init__(path)
        self._full = path
        self.setToolTip(path)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, self.width()))


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
        # workers de comptage lances : garde une reference (sinon GC des
        # signaux) ; liberes avec le dialogue, qui est de courte duree
        self._count_workers = []

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

        # boutons de validation : Annuler a gauche, Enregistrer a droite
        buttons = QHBoxLayout()
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
        buttons.addStretch(1)
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

        path_lbl = _ElidedPathLabel(folder)
        path_lbl.setObjectName("fmPath")
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
        self._count_workers.append(worker)
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
                color: {theme.ON_ACCENT};
                background: {theme.ACCENT};
                border: none;
                border-radius: 8px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton#fmSave:hover {{ background: {theme.ACCENT_HOVER}; }}
        """)


# ---------------------------------------------------------------- styles communs

def _dialog_css(c):
    return f"""
        QDialog {{ background: {c['window']}; }}
        QLabel {{ color: {c['text']}; }}
        QLabel#hint {{ color: {c['text_dim']}; font-size: 12px; }}
        QGroupBox {{
            color: {c['text']}; font-weight: 700;
            border: 1px solid {c['border']}; border-radius: 8px;
            margin-top: 14px; padding: 12px 12px 10px 12px;
        }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
        QCheckBox {{ color: {c['text']}; }}
        QPushButton {{
            color: {c['text']}; background: {c['button']};
            border: 1px solid {c['border']}; border-radius: 8px; padding: 6px 14px;
        }}
        QPushButton:hover {{ background: {c['button_hover']}; }}
        QPushButton:focus {{ border: 2px solid {theme.ACCENT}; }}
        QPushButton:disabled {{ color: {c['text_disabled']}; background: transparent; }}
        QPushButton#primary {{
            color: {theme.ON_ACCENT}; background: {theme.ACCENT}; border: none; font-weight: 700;
        }}
        QPushButton#primary:hover {{ background: {theme.ACCENT_HOVER}; }}
        QSpinBox {{
            color: {c['text']}; background: {c['panel']};
            border: 1px solid {c['border']}; border-radius: 5px; padding: 3px 6px;
        }}
    """


def _buttons_row(dialog, ok_label):
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton("Annuler")
    cancel.clicked.connect(dialog.reject)
    ok = QPushButton(ok_label)
    ok.setObjectName("primary")
    ok.setDefault(True)
    ok.clicked.connect(dialog.accept)
    row.addWidget(cancel)
    row.addWidget(ok)
    return row


# ---------------------------------------------------------------- preferences

# couleurs d'accentuation proposees (la premiere est celle d'origine), toutes
# lisibles telles quelles dans les deux themes ; toute autre couleur reste
# possible par « Personnalisée… »
ACCENT_PRESETS = [("Rouge Behelit", theme.DEFAULT_ACCENT), ("Orange", "#ce6e24"),
                  ("Ambre", "#b57b10"), ("Vert", "#2d9959"), ("Turquoise", "#1d9593"),
                  ("Bleu", "#2f7fd6"), ("Violet", "#8e5bd6"), ("Rose", "#d6457f")]


class PreferencesDialog(QDialog):
    """Reglages de l'application, en onglets. Les preferences simples ne sont
    ecrites qu'a la validation (save) ; les actions (vider un cache, exporter,
    importer, se connecter a AniList) agissent tout de suite, via les
    fonctions fournies par l'appelant :

    actions = {"clear_thumbs", "clear_meta", "export", "import"} -> fonctions ;
    tracker = AniListTracker ou None."""

    def __init__(self, store, colors, actions, tracker=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.c = colors
        self.actions = actions
        self.tracker = tracker
        self.setWindowTitle("Préférences")
        self.setMinimumWidth(620)
        self.setStyleSheet(_dialog_css(colors) + f"""
            QToolButton#accentSwatch {{ background: transparent; border: none;
                                        border-radius: 15px; }}
            QToolButton#accentSwatch:focus {{ border: 1px solid {colors['text_dim']}; }}
            QTabWidget::pane {{ border: 1px solid {colors['border']}; border-radius: 8px;
                                top: -1px; background: {colors['window']}; }}
            QTabBar::tab {{ color: {colors['text_dim']}; background: transparent;
                            padding: 6px 14px; border: none; }}
            QTabBar::tab:selected {{ color: {colors['text']};
                                     border-bottom: 2px solid {theme.ACCENT}; }}
            QScrollArea#shortcutScroll, #shortcutHost {{ background: transparent; border: none; }}
            QLabel#shortcutGroup {{ font-size: 15px; font-weight: 700; }}
        """ + sections_css(colors))
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        tabs = QTabWidget()
        root.addWidget(tabs)
        tabs.addTab(self._general_tab(), "Général")
        tabs.addTab(self._reader_tab(), "Lecteur")
        tabs.addTab(self._data_tab(), "Données")
        tabs.addTab(self._anilist_tab(), "AniList")
        tabs.addTab(self._shortcuts_tab(), "Raccourcis")
        self.tabs = tabs
        root.addSpacing(8)
        root.addLayout(_buttons_row(self, "Enregistrer"))
        # Qt plafonne la taille initiale d'une fenetre aux 2/3 de l'ecran : sur
        # un ecran de 900 px de haut, l'onglet General etait ecrase (lignes
        # rognees). On prend la taille voulue, dans la limite de l'ecran.
        self.ensurePolished()
        wanted = self.sizeHint()
        screen = (parent.screen() if parent is not None else QApplication.primaryScreen())
        self.resize(wanted.width(),
                    min(wanted.height(), screen.availableGeometry().height() - 60))

    # ----- helpers -----
    @staticmethod
    def _page():
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)
        return w, v

    @staticmethod
    def _hint(text):
        lab = QLabel(text)
        lab.setObjectName("hint")
        lab.setWordWrap(True)
        return lab

    def _confirm(self, title, text):
        return QMessageBox.question(self, title, text, QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No) == QMessageBox.Yes

    # ----- onglets -----
    def _general_tab(self):
        w, v = self._page()
        g = QGroupBox("Apparence et bibliothèque")
        # l'indication sur plusieurs lignes est hors du formulaire : QFormLayout
        # ne lui reserve pas sa hauteur et ecrase les lignes voisines
        gv = QVBoxLayout(g)
        f = QFormLayout()
        gv.addLayout(f)
        s = self.store
        self.theme = QComboBox()
        self.theme.addItem("Sombre", "dark")
        self.theme.addItem("Clair", "light")
        self.theme.setCurrentIndex(0 if s.ui_pref("theme", "dark") == "dark" else 1)
        f.addRow("Thème", self.theme)
        self.view_mode = QComboBox()
        self.view_mode.addItem("Grille de couvertures", "grid")
        self.view_mode.addItem("Liste compacte", "list")
        self.view_mode.setCurrentIndex(1 if s.library_pref("view_mode", "grid") == "list" else 0)
        f.addRow("Affichage", self.view_mode)
        f.addRow("Couleur d'accentuation", self._accent_row())
        self.accent_hint = self._hint("")
        gv.addWidget(self.accent_hint)
        self.theme.currentIndexChanged.connect(lambda _i: self._set_accent(self._accent))
        self._set_accent(s.ui_pref("accent"))
        # cases sur deux colonnes : l'onglet doit tenir sur un petit ecran
        checks = QGridLayout()
        checks.setContentsMargins(0, 0, 0, 0)
        self.group_series = QCheckBox("Regrouper les tomes par série")
        self.group_series.setToolTip("Les tomes d'un même manga sont rassemblés dans un "
                                     "dossier de série")
        self.group_series.setChecked(bool(s.library_pref("group_series", False)))
        checks.addWidget(self.group_series, 0, 0)
        self.show_continue = QCheckBox("Afficher « Continuer la lecture »")
        self.show_continue.setChecked(bool(s.library_pref("show_continue", True)))
        checks.addWidget(self.show_continue, 0, 1)
        self.show_details = QCheckBox("Afficher le panneau d'informations")
        self.show_details.setChecked(bool(s.library_pref("show_details", False)))
        checks.addWidget(self.show_details, 1, 0)
        gv.addLayout(checks)
        v.addWidget(g)

        g = QGroupBox("Discrétion")
        f = QFormLayout(g)
        self.boss_key = QCheckBox("Touche C : masquer la fenêtre du lecteur")
        self.boss_key.setChecked(bool(s.reader_pref("boss_key", True)))
        f.addRow(self.boss_key)
        self.global_hotkey = QCheckBox(
            "Ctrl + Alt + C : masquer / réafficher Beheread depuis n'importe où")
        self.global_hotkey.setChecked(bool(s.ui_pref("global_hotkey", True)))
        f.addRow(self.global_hotkey)
        v.addWidget(g)

        g = QGroupBox("Métadonnées en ligne")
        gv = QVBoxLayout(g)
        self.online = QCheckBox("Rechercher automatiquement l'auteur et l'année sur Internet")
        self.online.setChecked(s.ui_pref("online_metadata") is True)
        gv.addWidget(self.online)
        gv.addWidget(self._hint(
            "Le nom de la série (déduit du nom de fichier) et le numéro de tome sont envoyés "
            "à Google Books, AniList et MangaDex. Sans cette option, seules les informations "
            "ComicInfo.xml contenues dans les fichiers sont utilisées. Votre progression de "
            "lecture ne quitte jamais votre ordinateur (sauf suivi AniList, si vous l'activez)."))
        btn = QPushButton("Oublier les métadonnées téléchargées…")
        btn.clicked.connect(self._clear_meta)
        gv.addWidget(btn, alignment=Qt.AlignLeft)
        v.addWidget(g)
        v.addStretch(1)
        return w

    # ----- couleur d'accentuation -----
    def _accent_row(self):
        """Pastilles des couleurs proposees, couleur libre et retour a la
        couleur d'origine."""
        # un widget, pas un simple layout : QFormLayout ne reserve pas la
        # hauteur d'un layout imbrique (boutons ecrases, pastilles debordantes)
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self._swatches = {}
        for label, value in ACCENT_PRESETS:
            btn = QToolButton()
            btn.setObjectName("accentSwatch")
            btn.setCheckable(True)
            btn.setFixedSize(30, 30)
            btn.setIconSize(QSize(26, 26))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(label)
            btn.setAccessibleName(f"Couleur d'accentuation : {label}")
            btn.clicked.connect(lambda _checked=False, v=value: self._set_accent(v))
            self._swatches[value] = btn
            row.addWidget(btn)
        row.addSpacing(8)
        self.accent_custom = QPushButton("Personnalisée…")
        self.accent_custom.clicked.connect(self._pick_accent)
        row.addWidget(self.accent_custom)
        self.accent_reset = QPushButton("Réinitialiser")
        self.accent_reset.setToolTip("Revenir à la couleur d'origine")
        self.accent_reset.clicked.connect(lambda: self._set_accent(None))
        row.addWidget(self.accent_reset)
        row.addStretch(1)
        return host

    def _pick_accent(self):
        color = QColorDialog.getColor(QColor(self._accent), self, "Couleur d'accentuation")
        if color.isValid():
            self._set_accent(color.name())

    def _set_accent(self, value):
        """Couleur choisie dans le dialogue (None ou valeur invalide = couleur
        d'origine) ; enregistree par save()."""
        self._accent = theme.normalize_accent(value) or theme.DEFAULT_ACCENT
        ring = self.c["text"]
        for preset, btn in self._swatches.items():
            chosen = preset == self._accent
            btn.setChecked(chosen)
            btn.setIcon(icons.swatch(preset, ring if chosen else None))
        custom = self._accent not in self._swatches
        self.accent_custom.setIcon(icons.swatch(self._accent, ring) if custom else QIcon())
        self.accent_reset.setEnabled(self._accent != theme.DEFAULT_ACCENT)
        # une seule ligne dans tous les cas : la hauteur du dialogue ne bouge pas
        mode = self.theme.currentData()
        if theme.bounded_accent(self._accent, mode) == self._accent:
            hint = "L'icône des raccourcis et des fichiers dans Windows garde sa couleur d'origine."
        elif mode == "light":
            hint = ("Trop claire pour le thème clair : elle y sera assombrie juste assez "
                    "pour rester lisible.")
        else:
            hint = ("Trop sombre pour le thème sombre : elle y sera éclaircie juste assez "
                    "pour rester lisible.")
        self.accent_hint.setText(hint)

    def _shortcuts_tab(self):
        """Tous les raccourcis clavier (la carte d'aide F1 montre ceux de
        l'ecran courant ; ici, bibliotheque et lecteur a la suite)."""
        w, v = self._page()
        scroll = QScrollArea()
        scroll.setObjectName("shortcutScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # la liste defile dans la place laissee par les autres onglets, sans
        # agrandir le dialogue
        scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        host = QWidget()
        host.setObjectName("shortcutHost")
        hv = QVBoxLayout(host)
        hv.setContentsMargins(0, 0, 10, 0)
        hv.setSpacing(12)
        for title, sections in (("Dans la bibliothèque", LIBRARY_SHORTCUTS),
                                ("Dans le lecteur", READER_SHORTCUTS)):
            head = QLabel(title)
            head.setObjectName("shortcutGroup")
            hv.addWidget(head)
            hv.addLayout(sections_layout(sections, host, vertical=True))
            hv.addSpacing(8)
        hv.addStretch(1)
        scroll.setWidget(host)
        v.addWidget(scroll)
        return w

    def _reader_tab(self):
        w, v = self._page()
        s = self.store
        g = QGroupBox("Réglages du lecteur")
        f = QFormLayout(g)
        self.direction = QComboBox()
        self.direction.addItem("Manga : de droite à gauche", True)
        self.direction.addItem("Occidental : de gauche à droite", False)
        self.direction.setCurrentIndex(0 if s.reader_pref("manga_mode", True) else 1)
        f.addRow("Sens de lecture", self.direction)
        self.fit = QComboBox()
        for value, label in FIT_NAMES.items():
            self.fit.addItem(label, value)
        self.fit.setCurrentIndex(self.fit.findData(normalize_fit(s.reader_pref("fit_mode"))))
        f.addRow("Ajustement", self.fit)
        self.double_page = QCheckBox("Double page")
        self.double_page.setChecked(bool(s.reader_pref("double_page", True)))
        f.addRow(self.double_page)
        self.ambilight = QCheckBox("Ambilight : fond teinté par la couleur de la page")
        self.ambilight.setChecked(bool(s.reader_pref("ambilight", False)))
        f.addRow(self.ambilight)
        self.page_fade = QCheckBox("Fondu entre les pages")
        self.page_fade.setChecked(bool(s.reader_pref("page_fade", True)))
        f.addRow(self.page_fade)
        f.addRow(self._hint("Ces réglages valent pour tous les mangas. Seul le sens de lecture "
                            "fait exception : il est détecté automatiquement, et celui choisi "
                            "pour une série (touche M) reste prioritaire."))
        v.addWidget(g)
        v.addStretch(1)
        return w

    def _data_tab(self):
        w, v = self._page()
        s = self.store

        g = QGroupBox("Sauvegarde")
        gv = QVBoxLayout(g)
        gv.addWidget(self._hint(
            "Exporte dans un fichier la progression, les statistiques, les regroupements et "
            "les informations saisies à la main (par exemple pour passer à un autre PC). "
            "L'import fusionne : pour chaque tome, la progression la plus récente l'emporte, "
            "et vos réglages actuels ne sont pas écrasés."))
        row = QHBoxLayout()
        exp = QPushButton("Exporter…")
        exp.clicked.connect(lambda: self._report(self.actions["export"]()))
        imp = QPushButton("Importer…")
        imp.clicked.connect(lambda: self._report(self.actions["import"]()))
        row.addWidget(exp)
        row.addWidget(imp)
        row.addStretch(1)
        gv.addLayout(row)
        v.addWidget(g)

        g = QGroupBox("Données locales")
        gv = QVBoxLayout(g)
        path = QLabel(str(s.dir))
        path.setObjectName("hint")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        gv.addWidget(path)
        row = QHBoxLayout()
        open_btn = QPushButton("Ouvrir le dossier des données")
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(s.dir))))
        row.addWidget(open_btn)
        thumbs_btn = QPushButton("Vider le cache des vignettes…")
        thumbs_btn.clicked.connect(self._clear_thumbs)
        row.addWidget(thumbs_btn)
        row.addStretch(1)
        gv.addLayout(row)
        v.addWidget(g)
        self.status = self._hint("")
        v.addWidget(self.status)
        v.addStretch(1)
        return w

    def _anilist_tab(self):
        w, v = self._page()
        v.addWidget(self._hint(
            "Connectez votre compte AniList : à la fin de chaque séance de lecture, Beheread "
            "met à jour votre liste (nombre de tomes ou de chapitres lus). La progression "
            "n'est jamais diminuée, et une série que vous avez marquée terminée, en pause ou "
            "abandonnée n'est jamais modifiée."))
        g = QGroupBox("Compte AniList")
        gv = QVBoxLayout(g)
        self.al_state = QLabel()
        gv.addWidget(self.al_state)
        row = QHBoxLayout()
        self.al_login = QPushButton("Se connecter à AniList…")
        self.al_login.setObjectName("primary")
        self.al_login.clicked.connect(self._anilist_login)
        self.al_logout = QPushButton("Se déconnecter")
        self.al_logout.clicked.connect(self._anilist_logout)
        row.addWidget(self.al_login)
        row.addWidget(self.al_logout)
        row.addStretch(1)
        gv.addLayout(row)
        gv.addWidget(self._hint(
            "Votre navigateur s'ouvre sur AniList pour autoriser Beheread ; la connexion se "
            "termine ensuite toute seule. L'accès est chiffré sur ce PC (protection Windows "
            "liée à votre session), reste valable un an, et peut être révoqué à tout moment "
            "depuis les réglages de votre compte AniList."))
        self.tracking = QCheckBox("Mettre à jour ma liste à la fin de chaque séance de lecture")
        self.tracking.setChecked(bool(self.store.anilist().get("tracking", True)))
        gv.addWidget(self.tracking)
        self.al_status = self._hint(self.tracker.status if self.tracker else "")
        gv.addWidget(self.al_status)
        if self.tracker is not None:
            self.tracker.statusChanged.connect(self.al_status.setText)
        v.addWidget(g)
        v.addStretch(1)
        self._refresh_anilist()
        return w

    # ----- AniList -----
    def _refresh_anilist(self):
        a = self.store.anilist()
        connected = bool(a.get("token_enc"))
        configured = bool(config.anilist_client_id())
        if connected:
            self.al_state.setText(f"Connecté en tant que <b>{html.escape(a.get('user') or '?')}</b>.")
        elif configured:
            self.al_state.setText("Non connecté.")
        else:
            self.al_state.setText("Le suivi AniList n'est pas disponible dans cette version "
                                  "de Beheread.")
        self.al_login.setVisible(not connected)
        self.al_login.setEnabled(configured)
        self.al_logout.setVisible(connected)
        self.tracking.setEnabled(connected)

    def _anilist_login(self):
        dlg = AniListLoginDialog(self.store, self)
        dlg.exec()
        self._refresh_anilist()

    def _anilist_logout(self):
        if self._confirm("Se déconnecter d'AniList",
                         "Oublier l'accès AniList enregistré sur ce PC ?"):
            self.store.set_anilist_login(None, None)
            self._refresh_anilist()

    # ----- caches -----
    def _clear_thumbs(self):
        if self._confirm("Vider le cache des vignettes",
                         "Supprimer les vignettes en cache ? Elles seront recréées "
                         "à l'affichage."):
            n = self.actions["clear_thumbs"]()
            self.status.setText(f"{n} vignette(s) supprimée(s).")

    def _clear_meta(self):
        if self._confirm("Oublier les métadonnées téléchargées",
                         "Oublier les auteurs et dates obtenus en ligne ? Les "
                         "informations issues de ComicInfo.xml ou saisies à la main "
                         "sont conservées."):
            n = self.actions["clear_meta"]()
            self.status.setText(f"{n} entrée(s) de métadonnées oubliée(s).")

    def save(self):
        """Ecrit les preferences choisies (appele par la bibliotheque apres
        acceptation du dialogue)."""
        s = self.store
        s.set_ui_pref("theme", self.theme.currentData())
        # None = couleur d'origine (elle suivrait un changement de la valeur par defaut)
        s.set_ui_pref("accent", None if self._accent == theme.DEFAULT_ACCENT else self._accent)
        s.set_library_pref("view_mode", self.view_mode.currentData())
        s.set_library_pref("group_series", self.group_series.isChecked())
        s.set_library_pref("show_continue", self.show_continue.isChecked())
        s.set_library_pref("show_details", self.show_details.isChecked())
        s.set_reader_pref("manga_mode", bool(self.direction.currentData()))
        s.set_reader_pref("fit_mode", int(self.fit.currentData()))
        s.set_reader_pref("double_page", self.double_page.isChecked())
        s.set_reader_pref("ambilight", self.ambilight.isChecked())
        s.set_reader_pref("page_fade", self.page_fade.isChecked())
        s.set_reader_pref("boss_key", self.boss_key.isChecked())
        s.set_ui_pref("global_hotkey", self.global_hotkey.isChecked())
        s.set_anilist_value("tracking", self.tracking.isChecked())
        # une case decochee apres un choix vaut refus explicite ; si
        # l'utilisateur n'a jamais repondu et laisse decoche, on garde « pas
        # encore repondu » (le bandeau de consentement reste propose)
        if self.online.isChecked():
            s.set_ui_pref("online_metadata", True)
        elif s.ui_pref("online_metadata") is not None:
            s.set_ui_pref("online_metadata", False)


# ---------------------------------------------------------------- connexion AniList

class AniListLoginDialog(QDialog):
    """Fenetre d'attente pendant que l'utilisateur autorise Beheread dans son
    navigateur. Le jeton revient par LocalAuthReceiver, est verifie aupres
    d'AniList (compte associe), puis enregistre chiffre."""

    TIMEOUT_MS = 5 * 60 * 1000

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Connexion à AniList")
        self.setMinimumWidth(440)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        self.message = QLabel("Autorisez Beheread dans la page AniList qui vient de s'ouvrir "
                              "dans votre navigateur…")
        self.message.setWordWrap(True)
        v.addWidget(self.message)
        row = QHBoxLayout()
        self.reopen = QPushButton("Rouvrir la page")
        self.reopen.clicked.connect(self._open_browser)
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        row.addWidget(self.reopen)
        row.addStretch(1)
        row.addWidget(cancel)
        v.addSpacing(8)
        v.addLayout(row)

        self.receiver = LocalAuthReceiver(config.ANILIST_REDIRECT_PORT,
                                          config.ANILIST_REDIRECT_PATH, self)
        self.receiver.tokenReceived.connect(self._on_token)
        self.receiver.failed.connect(self._on_failed)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(lambda: self._on_failed("Délai dépassé."))
        QTimer.singleShot(0, self._start)

    def _start(self):
        try:
            self.receiver.start()
        except OSError:
            self._fail_hard(f"Le port local {config.ANILIST_REDIRECT_PORT} est déjà utilisé "
                            "par une autre application : fermez-la puis réessayez.")
            return
        self._timeout.start(self.TIMEOUT_MS)
        self._open_browser()

    def _open_browser(self):
        QDesktopServices.openUrl(QUrl(anilist.authorize_url(config.anilist_client_id())))

    def _on_token(self, token):
        self._timeout.stop()
        self.message.setText("Vérification du compte…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            user = anilist.viewer(token)
        except anilist.AniListError as e:
            QApplication.restoreOverrideCursor()
            self._fail_hard(f"AniList n'a pas validé la connexion :\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.store.set_anilist_login(token, user.get("name"))
        self.accept()

    def _on_failed(self, reason):
        self._fail_hard(f"Connexion non aboutie ({reason}).")

    def _fail_hard(self, text):
        self.receiver.stop()
        self._timeout.stop()
        self.message.setText(text)
        self.reopen.hide()

    def done(self, result):
        self.receiver.stop()
        self._timeout.stop()
        super().done(result)


# ---------------------------------------------------------------- saisie manuelle

class EditInfoDialog(QDialog):
    """Saisie manuelle de l'auteur et de l'annee d'un tome ou d'une serie
    (source « manual » : prioritaire, et conservee par les nettoyages)."""

    def __init__(self, heading, author, year, colors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifier les informations")
        self.setMinimumWidth(420)
        self.setStyleSheet(_dialog_css(colors))
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        title = QLabel(heading)
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(title)
        f = QFormLayout()
        self.author = QLineEdit(author or "")
        self.author.setPlaceholderText("Inconnu")
        f.addRow("Auteur", self.author)
        self.year = QSpinBox()
        self.year.setRange(0, 2100)
        self.year.setSpecialValueText("Inconnue")
        self.year.setValue(int(year or 0))
        f.addRow("Année de sortie", self.year)
        root.addLayout(f)
        root.addSpacing(8)
        root.addLayout(_buttons_row(self, "Enregistrer"))

    def values(self):
        """(auteurs, annee) saisis : liste vide / None si laisses vides."""
        author = self.author.text().strip()
        return ([author] if author else []), (self.year.value() or None)
