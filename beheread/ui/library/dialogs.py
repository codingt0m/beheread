"""Boites de dialogue de la bibliotheque : gestion des dossiers sources
(panneau facon Plex), preferences, et saisie manuelle des informations d'un
tome ou d'une serie."""

import html
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPixmap
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
    QListWidget,
    QListWidgetItem,
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

from beheread import config, i18n, platforms
from beheread.i18n import N_, fmt_decimal, tr, trn
from beheread.infra import anilist, archive
from beheread.infra.anilist_auth import LocalAuthReceiver
from beheread.ui import icons, theme
from beheread.ui.flow import FlowLayout
from beheread.ui.help_overlay import (
    LIBRARY_SHORTCUTS,
    READER_SHORTCUTS,
    sections_css,
    sections_layout,
)
from beheread.ui.library.servers_ui import ServersTabMixin
from beheread.ui.library.workers import CallWorker, PagesWorker, _FolderCountWorker
from beheread.ui.reader.constants import FIT_NAMES, normalize_fit
from beheread.ui.safe_text import plain


class _ElidedPathLabel(QLabel):
    """Chemin raccourci au milieu (« … ») quand la place manque : un QLabel
    simple impose la largeur de tout son texte et poussait le bouton de
    retrait hors du dialogue."""

    def __init__(self, path):
        super().__init__(path)
        self._full = path
        self.setTextFormat(Qt.PlainText)   # chemin quelconque (voir ui/safe_text.py)
        self.setToolTip(plain(path))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, self.width()))


def format_size(size):
    """Taille lisible : « 850 Mo », « 12,4 Go » (« 12.4 GB » en anglais)."""
    for unit, factor in ((N_("To"), 1024 ** 4), (N_("Go"), 1024 ** 3), (N_("Mo"), 1024 ** 2)):
        if size >= factor:
            value = size / factor
            text = fmt_decimal(value) if value < 100 else f"{value:.0f}"
            return f"{text} {tr(unit)}"
    return f"{size // 1024} {tr('Ko')}"


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

        self.setWindowTitle(tr("Dossiers de la bibliothèque"))
        self.setMinimumWidth(560)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)

        title = QLabel(tr("Ajouter des dossiers à votre bibliothèque"))
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
        self.btn_browse = QPushButton(tr("  Parcourir et choisir un dossier"))
        self.btn_browse.setObjectName("fmBrowse")
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        self.btn_browse.setIcon(icons.folder_plus(self.c["text"]))
        self.btn_browse.clicked.connect(self._browse)
        browse_row = QHBoxLayout()
        browse_row.addStretch(1)
        browse_row.addWidget(self.btn_browse)
        browse_row.addStretch(1)
        root.addLayout(browse_row)

        self._empty = QLabel(tr("Aucun dossier source. Ajoutez-en un pour "
                                "constituer votre bibliothèque."))
        self._empty.setObjectName("fmEmpty")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setWordWrap(True)
        root.addWidget(self._empty)

        # boutons de validation : Annuler a gauche, Enregistrer a droite
        buttons = QHBoxLayout()
        self.btn_cancel = QPushButton(tr("Annuler"))
        self.btn_cancel.setObjectName("fmCancel")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton(tr("Enregistrer les modifications"))
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
        btn_x.setToolTip(tr("Retirer ce dossier"))
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

    def _on_count(self, folder, n, size=0):
        entry = self._rows.get(folder)
        if not entry:
            return
        _, count_lbl = entry
        if n < 0:
            count_lbl.setText(tr("dossier introuvable"))
        elif n == 0:
            count_lbl.setText(tr("aucun manga"))
        else:
            count_lbl.setText(trn(n, "{n} manga", "{n} mangas") + f" · {format_size(size)}")

    def _remove_row(self, folder):
        entry = self._rows.pop(folder, None)
        if entry:
            entry[0].setParent(None)
            entry[0].deleteLater()
        if folder in self._folders:
            self._folders.remove(folder)
        self._update_empty()

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Choisir un dossier de mangas"))
        if not folder:
            return
        folder = str(Path(folder))
        if folder in self._folders:
            QMessageBox.information(self, tr("Déjà présent"),
                                    tr("Ce dossier est déjà dans la bibliothèque."))
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
    cancel = QPushButton(tr("Annuler"))
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
# (noms traduits a l'affichage : tr)
ACCENT_PRESETS = [(N_("Rouge Behelit"), theme.DEFAULT_ACCENT), (N_("Orange"), "#ce6e24"),
                  (N_("Ambre"), "#b57b10"), (N_("Vert"), "#2d9959"), (N_("Turquoise"), "#1d9593"),
                  (N_("Bleu"), "#2f7fd6"), (N_("Violet"), "#8e5bd6"), (N_("Rose"), "#d6457f")]


class PreferencesDialog(ServersTabMixin, QDialog):
    """Reglages de l'application, en onglets. Les preferences simples ne sont
    ecrites qu'a la validation (save) ; les actions (vider un cache, exporter,
    importer, se connecter a AniList) agissent tout de suite, via les
    fonctions fournies par l'appelant :

    actions = {"clear_thumbs", "clear_meta", "export", "import"} -> fonctions ;
    tracker = AniListTracker ou None."""

    def __init__(self, store, colors, actions, tracker=None, parent=None, servers=None):
        super().__init__(parent)
        self.store = store
        self.c = colors
        self.actions = actions
        self.tracker = tracker
        self.servers = servers   # ServerManager (onglet Serveurs), ou None
        self.setWindowTitle(tr("Préférences"))
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
            QScrollArea#tabScroll, #tabPage {{ background: transparent; border: none; }}
            QPushButton#chip {{ border-radius: 12px; padding: 3px 10px; background: {colors['button']}; }}
            QLabel#shortcutGroup {{ font-size: 15px; font-weight: 700; }}
        """ + sections_css(colors))
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        tabs = QTabWidget()
        root.addWidget(tabs)
        # onglets defilants : sur un petit ecran, la fenetre reste a sa
        # hauteur (boutons visibles) et l'onglet defile au lieu de deborder
        tabs.addTab(self._scrolled(self._general_tab()), tr("Général"))
        tabs.addTab(self._scrolled(self._reader_tab()), tr("Lecteur"))
        tabs.addTab(self._scrolled(self._data_tab()), tr("Données"))
        tabs.addTab(self._scrolled(self._anilist_tab()), "AniList")
        tabs.addTab(self._scrolled(self._servers_tab()), tr("Serveurs"))
        tabs.addTab(self._shortcuts_tab(), tr("Raccourcis"))
        self.tabs = tabs
        root.addSpacing(8)
        root.addLayout(_buttons_row(self, tr("Enregistrer")))
        # Qt plafonne la taille initiale d'une fenetre aux 2/3 de l'ecran : sur
        # un ecran de 900 px de haut, l'onglet General etait ecrase (lignes
        # rognees). On prend la taille voulue, dans la limite de l'ecran.
        # Les onglets defilent : leur zone ne reclame plus la taille de son
        # contenu, prise donc sur les pages elles-memes (la plus grande).
        self.ensurePolished()
        wanted = self.sizeHint()
        pages = [tabs.widget(i).widget() for i in range(tabs.count())
                 if isinstance(tabs.widget(i), QScrollArea) and tabs.widget(i).objectName() == "tabScroll"]
        extra_w = wanted.width() - tabs.sizeHint().width()
        extra_h = wanted.height() - tabs.sizeHint().height() + tabs.tabBar().sizeHint().height() + 16
        width = max([wanted.width()] + [p.sizeHint().width() + extra_w + 24 for p in pages])
        height = max([wanted.height()] + [p.sizeHint().height() + extra_h for p in pages])
        screen = (parent.screen() if parent is not None else QApplication.primaryScreen())
        self.resize(width, min(height, screen.availableGeometry().height() - 60))

    # ----- helpers -----
    @staticmethod
    def _scrolled(page):
        """Onglet dans une zone defilante sans cadre (fond de l'onglet)."""
        area = QScrollArea()
        area.setObjectName("tabScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page.setObjectName("tabPage")
        area.setWidget(page)
        return area

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
        g = QGroupBox(tr("Apparence et bibliothèque"))
        # l'indication sur plusieurs lignes est hors du formulaire : QFormLayout
        # ne lui reserve pas sa hauteur et ecrase les lignes voisines
        gv = QVBoxLayout(g)
        f = QFormLayout()
        gv.addLayout(f)
        s = self.store
        self.theme = QComboBox()
        self.theme.addItem(tr("Sombre"), "dark")
        self.theme.addItem(tr("Clair"), "light")
        self.theme.setCurrentIndex(0 if s.ui_pref("theme", "dark") == "dark" else 1)
        f.addRow(tr("Thème"), self.theme)
        self.view_mode = QComboBox()
        self.view_mode.addItem(tr("Grille de couvertures"), "grid")
        self.view_mode.addItem(tr("Liste compacte"), "list")
        self.view_mode.setCurrentIndex(1 if s.library_pref("view_mode", "grid") == "list" else 0)
        f.addRow(tr("Affichage"), self.view_mode)
        f.addRow(tr("Langue"), self._language_row())
        f.addRow(tr("Couleur d'accentuation"), self._accent_row())
        self.accent_hint = self._hint("")
        gv.addWidget(self.accent_hint)
        self.theme.currentIndexChanged.connect(lambda _i: self._set_accent(self._accent))
        self._set_accent(s.ui_pref("accent"))
        # cases sur deux colonnes : l'onglet doit tenir sur un petit ecran
        checks = QGridLayout()
        checks.setContentsMargins(0, 0, 0, 0)
        self.group_series = QCheckBox(tr("Regrouper les tomes par série"))
        self.group_series.setToolTip(tr("Les tomes d'un même manga sont rassemblés dans un "
                                        "dossier de série"))
        self.group_series.setChecked(bool(s.library_pref("group_series", False)))
        checks.addWidget(self.group_series, 0, 0)
        self.show_continue = QCheckBox(tr("Afficher « Continuer la lecture »"))
        self.show_continue.setChecked(bool(s.library_pref("show_continue", True)))
        checks.addWidget(self.show_continue, 0, 1)
        self.show_details = QCheckBox(tr("Afficher le panneau d'informations"))
        self.show_details.setChecked(bool(s.library_pref("show_details", False)))
        checks.addWidget(self.show_details, 1, 0)
        # dossier de serie ouvert : cases « Non possede », chapitres redondants
        self.show_missing = QCheckBox(tr("Afficher les tomes et chapitres manquants"))
        self.show_missing.setToolTip(tr("Dans une série ouverte, une case « Non possédé » "
                                        "marque chaque tome ou chapitre manquant"))
        self.show_missing.setChecked(bool(s.library_pref("show_missing", True)))
        checks.addWidget(self.show_missing, 1, 1)
        self.show_covered = QCheckBox(tr("Afficher les chapitres déjà inclus dans un tome"))
        self.show_covered.setToolTip(tr("Chapitres qu'un tome possédé contient déjà (découpage "
                                        "de MangaDex). Ceux d'un tome virtuel se lisent en "
                                        "ouvrant ce tome."))
        self.show_covered.setChecked(bool(s.library_pref("show_covered_chapters", False)))
        checks.addWidget(self.show_covered, 2, 0)
        gv.addLayout(checks)
        v.addWidget(g)

        g = QGroupBox(tr("Discrétion"))
        f = QFormLayout(g)
        self.boss_key = QCheckBox(tr("Touche C : masquer la fenêtre du lecteur"))
        self.boss_key.setChecked(bool(s.reader_pref("boss_key", True)))
        f.addRow(self.boss_key)
        self.global_hotkey = QCheckBox(
            tr("Ctrl + Alt + C : masquer / réafficher Beheread depuis n'importe où"))
        self.global_hotkey.setChecked(bool(s.ui_pref("global_hotkey", True)))
        if platforms.GLOBAL_HOTKEY:   # pas de raccourci global sous macOS
            f.addRow(self.global_hotkey)
        v.addWidget(g)

        g = QGroupBox(tr("Métadonnées en ligne"))
        gv = QVBoxLayout(g)
        self.online = QCheckBox(tr("Rechercher automatiquement l'auteur et l'année sur Internet"))
        self.online.setChecked(s.ui_pref("online_metadata") is True)
        gv.addWidget(self.online)
        gv.addWidget(self._hint(
            tr("Le nom de la série (déduit du nom de fichier) et le numéro de tome sont envoyés "
               "à Google Books, AniList, MangaDex et la BnF. Sans cette option, seules les informations "
               "ComicInfo.xml contenues dans les fichiers sont utilisées. Votre progression de "
               "lecture ne quitte jamais votre ordinateur (sauf suivi AniList, si vous l'activez).")))
        btn = QPushButton(tr("Oublier les métadonnées téléchargées…"))
        btn.clicked.connect(self._clear_meta)
        gv.addWidget(btn, alignment=Qt.AlignLeft)
        v.addWidget(g)

        g = QGroupBox(tr("Mises à jour"))
        gv = QVBoxLayout(g)
        self.check_updates = QCheckBox(
            tr("Vérifier une fois par jour si une nouvelle version est disponible"))
        self.check_updates.setChecked(bool(s.ui_pref("check_updates", False)))
        gv.addWidget(self.check_updates)
        gv.addWidget(self._hint(
            tr("Beheread consulte la liste des versions publiées sur GitHub. Rien d'autre n'est "
               "envoyé, et rien n'est installé sans vous : un bandeau propose simplement de "
               "télécharger la nouvelle version.")))
        row = QHBoxLayout()
        now = QPushButton(tr("Vérifier maintenant"))
        now.clicked.connect(self._check_updates_now)
        row.addWidget(now)
        self.update_status = self._hint(self._last_update_check())
        self.update_status.setWordWrap(False)
        row.addWidget(self.update_status)
        row.addStretch(1)
        gv.addLayout(row)
        v.addWidget(g)
        v.addStretch(1)
        return w

    def _last_update_check(self):
        ts = float(self.store.ui_pref("update_checked", 0) or 0)
        if not ts:
            return tr("Jamais vérifié")
        when = time.localtime(ts)
        hour = time.strftime("%H:%M", when)
        if time.strftime("%Y%m%d", when) == time.strftime("%Y%m%d"):
            return tr("Dernière vérification : aujourd'hui à {hour}", hour=hour)
        return tr("Dernière vérification : le {day} à {hour}",
                  day=time.strftime(tr("%d/%m/%Y"), when), hour=hour)

    def _check_updates_now(self):
        if "check_updates" not in self.actions:
            return
        self.update_status.setText(tr("Vérification…"))
        self.actions["check_updates"](self.update_status.setText)

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
            label = tr(label)
            btn = QToolButton()
            btn.setObjectName("accentSwatch")
            btn.setCheckable(True)
            btn.setFixedSize(30, 30)
            btn.setIconSize(QSize(26, 26))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(label)
            btn.setAccessibleName(tr("Couleur d'accentuation : {name}", name=label))
            btn.clicked.connect(lambda _checked=False, v=value: self._set_accent(v))
            self._swatches[value] = btn
            row.addWidget(btn)
        row.addSpacing(8)
        self.accent_custom = QPushButton(tr("Personnalisée…"))
        self.accent_custom.clicked.connect(self._pick_accent)
        row.addWidget(self.accent_custom)
        self.accent_reset = QPushButton(tr("Réinitialiser"))
        self.accent_reset.setToolTip(tr("Revenir à la couleur d'origine"))
        self.accent_reset.clicked.connect(lambda: self._set_accent(None))
        row.addWidget(self.accent_reset)
        row.addStretch(1)
        return host

    def _language_row(self):
        """Langue de l'interface. Les textes sont traduits a la creation des
        fenetres : en changer redemarre Beheread (voir MainWindow.restart)."""
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        self.language = QComboBox()
        self.language.addItem(tr("Celle du système"), "system")
        for code, name in i18n.LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(
            max(0, self.language.findData(self.store.ui_pref("language", "system"))))
        row.addWidget(self.language)
        hint = self._hint(tr("Beheread redémarre pour l'appliquer"))
        hint.setWordWrap(False)
        row.addWidget(hint)
        row.addStretch(1)
        return host

    def _pick_accent(self):
        color = QColorDialog.getColor(QColor(self._accent), self, tr("Couleur d'accentuation"))
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
            hint = (tr("L'icône de l'application dans le Finder garde sa couleur d'origine.")
                    if platforms.IS_MACOS else
                    tr("L'icône des raccourcis et des fichiers dans Windows garde sa couleur d'origine."))
        elif mode == "light":
            hint = (tr("Trop claire pour le thème clair : elle y sera assombrie juste assez "
                       "pour rester lisible."))
        else:
            hint = (tr("Trop sombre pour le thème sombre : elle y sera éclaircie juste assez "
                       "pour rester lisible."))
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
        for title, sections in ((tr("Dans la bibliothèque"), LIBRARY_SHORTCUTS),
                                (tr("Dans le lecteur"), READER_SHORTCUTS)):
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
        g = QGroupBox(tr("Réglages du lecteur"))
        f = QFormLayout(g)
        self.direction = QComboBox()
        self.direction.addItem(tr("Manga : de droite à gauche"), True)
        self.direction.addItem(tr("Occidental : de gauche à droite"), False)
        self.direction.setCurrentIndex(0 if s.reader_pref("manga_mode", True) else 1)
        f.addRow(tr("Sens par défaut"), self.direction)
        self.fit = QComboBox()
        for value, label in FIT_NAMES.items():
            self.fit.addItem(tr(label), value)
        self.fit.setCurrentIndex(self.fit.findData(normalize_fit(s.reader_pref("fit_mode"))))
        f.addRow(tr("Ajustement"), self.fit)
        self.double_page = QCheckBox(tr("Double page"))
        self.double_page.setChecked(bool(s.reader_pref("double_page", True)))
        f.addRow(self.double_page)
        self.ambilight = QCheckBox(tr("Ambilight : fond teinté par la couleur de la page"))
        self.ambilight.setChecked(bool(s.reader_pref("ambilight", False)))
        f.addRow(self.ambilight)
        self.page_fade = QCheckBox(tr("Fondu entre les pages"))
        self.page_fade.setChecked(bool(s.reader_pref("page_fade", True)))
        f.addRow(self.page_fade)
        f.addRow(self._hint(tr("Ces réglages valent pour tous les mangas. Seul le sens de lecture "
                               "fait exception : il est détecté automatiquement (manga, BD), et "
                               "celui choisi pour une série (touche M) reste prioritaire. Le sens "
                               "par défaut ne sert qu'aux séries que rien ne permet de reconnaître.")))
        v.addWidget(g)

        g = QGroupBox(tr("Fiche de fin de tome"))
        gv = QVBoxLayout(g)
        self.babelio = QCheckBox(tr("Proposer « Marquer comme lu sur Babelio »"))
        self.babelio.setChecked(bool(s.reader_pref("babelio_button", False)))
        gv.addWidget(self.babelio)
        gv.addWidget(self._hint(
            tr("Ouvre la recherche du tome sur babelio.com dans votre navigateur ; c'est vous qui "
               "le marquez « lu ». Beheread ne se connecte pas à Babelio et n'y envoie que le "
               "titre du tome, à votre clic.")))
        v.addWidget(g)
        v.addStretch(1)
        return w

    def _data_tab(self):
        w, v = self._page()
        s = self.store

        g = QGroupBox(tr("Sauvegarde"))
        gv = QVBoxLayout(g)
        gv.addWidget(self._hint(
            tr("Exporte dans un fichier la progression, les statistiques, les regroupements et "
               "les informations saisies à la main (par exemple pour passer à un autre PC). "
               "L'import fusionne : pour chaque tome, la progression la plus récente l'emporte, "
               "et vos réglages actuels ne sont pas écrasés.")))
        row = QHBoxLayout()
        exp = QPushButton(tr("Exporter…"))
        exp.clicked.connect(lambda: self._report(self.actions["export"]()))
        imp = QPushButton(tr("Importer…"))
        imp.clicked.connect(lambda: self._report(self.actions["import"]()))
        row.addWidget(exp)
        row.addWidget(imp)
        row.addStretch(1)
        gv.addLayout(row)
        v.addWidget(g)

        g = QGroupBox(tr("Journal de lecture"))
        gv = QVBoxLayout(g)
        gv.addWidget(self._hint(
            tr("Chaque jour de lecture, tome par tome : date, série, tome, pages lues, temps "
               "de lecture, tome terminé. Lisible par Excel, LibreOffice ou Google Sheets.")))
        row = QHBoxLayout()
        csv_btn = QPushButton(tr("Exporter en CSV…"))
        csv_btn.clicked.connect(lambda: self._report(self.actions["export_csv"]()))
        row.addWidget(csv_btn)
        lines = len(s.reading_log.csv_rows())
        count = self._hint(trn(lines, "Tous les appareils · {n} ligne",
                               "Tous les appareils · {n} lignes"))
        count.setWordWrap(False)
        row.addWidget(count)
        row.addStretch(1)
        gv.addLayout(row)
        v.addWidget(g)

        v.addWidget(self._extra_words_group())

        g = QGroupBox(tr("Données locales"))
        gv = QVBoxLayout(g)
        path = QLabel(str(s.dir))
        path.setObjectName("hint")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        gv.addWidget(path)
        row = QHBoxLayout()
        open_btn = QPushButton(tr("Ouvrir le dossier des données"))
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(s.dir))))
        row.addWidget(open_btn)
        thumbs_btn = QPushButton(tr("Vider le cache des vignettes…"))
        thumbs_btn.clicked.connect(self._clear_thumbs)
        row.addWidget(thumbs_btn)
        row.addStretch(1)
        gv.addLayout(row)
        v.addWidget(g)
        self.status = self._hint("")
        v.addWidget(self.status)
        v.addStretch(1)
        return w

    # ----- pages ignorees (credits des equipes de traduction) -----
    def _extra_words_group(self):
        g = QGroupBox(tr("Pages ignorées"))
        gv = QVBoxLayout(g)
        gv.addWidget(self._hint(
            tr("Les images dont le nom contient l'un de ces mots ne sont pas comptées comme "
               "des pages : crédits et recrutement des équipes de traduction. Un tome n'est "
               "jamais vidé.")))
        words = self.store.library_pref("extra_page_words")
        self._extra_words = list(archive.DEFAULT_EXTRA_PAGE_WORDS if words is None else words)
        self._chips_host = QWidget()
        self._chips = FlowLayout(self._chips_host, spacing=6)
        gv.addWidget(self._chips_host)
        row = QHBoxLayout()
        label = QLabel(tr("Ajouter un mot"))
        label.setObjectName("hint")
        row.addWidget(label)
        self._new_word = QLineEdit()
        self._new_word.setPlaceholderText(tr("ex. teamscan"))
        self._new_word.setMaximumWidth(200)
        self._new_word.returnPressed.connect(self._add_extra_word)
        label.setBuddy(self._new_word)
        row.addWidget(self._new_word)
        add = QPushButton(tr("Ajouter"))
        add.clicked.connect(self._add_extra_word)
        row.addWidget(add)
        row.addStretch(1)
        reset = QPushButton(tr("Rétablir les mots d'origine"))
        reset.clicked.connect(self._reset_extra_words)
        row.addWidget(reset)
        gv.addLayout(row)
        self._refresh_extra_chips()
        return g

    @staticmethod
    def _extra_word_label(word):
        return tr("Commence par « {word} »", word=word[1:]) if word.startswith("^") else word

    def _refresh_extra_chips(self):
        while self._chips.count():
            w = self._chips.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for word in self._extra_words:
            chip = QPushButton(f"{self._extra_word_label(word)}   ×")
            chip.setObjectName("chip")
            chip.setToolTip(tr("Retirer ce mot"))
            chip.setAccessibleName(tr("Retirer « {word} »", word=self._extra_word_label(word)))
            chip.clicked.connect(lambda _c=False, w=word: self._remove_extra_word(w))
            self._chips.addWidget(chip)

    def _add_extra_word(self):
        word = self._new_word.text().strip().lower()
        if word and word.lstrip("^") and word not in self._extra_words:
            self._extra_words.append(word)
            self._refresh_extra_chips()
        self._new_word.clear()

    def _remove_extra_word(self, word):
        if word in self._extra_words:
            self._extra_words.remove(word)
            self._refresh_extra_chips()

    def _reset_extra_words(self):
        self._extra_words = list(archive.DEFAULT_EXTRA_PAGE_WORDS)
        self._refresh_extra_chips()

    def _anilist_tab(self):
        w, v = self._page()
        v.addWidget(self._hint(
            tr("Connectez votre compte AniList : à la fin de chaque séance de lecture, Beheread "
               "met à jour votre liste (nombre de tomes ou de chapitres lus). La progression "
               "n'est jamais diminuée, et une série que vous avez marquée terminée, en pause ou "
               "abandonnée n'est jamais modifiée.")))
        g = QGroupBox(tr("Compte AniList"))
        gv = QVBoxLayout(g)
        self.al_state = QLabel()
        gv.addWidget(self.al_state)
        row = QHBoxLayout()
        self.al_login = QPushButton(tr("Se connecter à AniList…"))
        self.al_login.setObjectName("primary")
        self.al_login.clicked.connect(self._anilist_login)
        self.al_logout = QPushButton(tr("Se déconnecter"))
        self.al_logout.clicked.connect(self._anilist_logout)
        row.addWidget(self.al_login)
        row.addWidget(self.al_logout)
        row.addStretch(1)
        gv.addLayout(row)
        gv.addWidget(self._hint(
            tr("Votre navigateur s'ouvre sur AniList pour autoriser Beheread ; la connexion se "
               "termine ensuite toute seule.") + " "
            + (tr("L'accès est rangé dans le Trousseau de ce Mac, reste valable un an, et peut "
                  "être révoqué à tout moment depuis les réglages de votre compte AniList.")
               if platforms.IS_MACOS else
               tr("L'accès est chiffré sur ce PC (protection Windows liée à votre session), "
                  "reste valable un an, et peut être révoqué à tout moment depuis les "
                  "réglages de votre compte AniList."))))
        self.tracking = QCheckBox(tr("Mettre à jour ma liste à la fin de chaque séance de lecture"))
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
            self.al_state.setText(tr("Connecté en tant que {user}.",
                                     user=f"<b>{html.escape(a.get('user') or '?')}</b>"))
        elif configured:
            self.al_state.setText(tr("Non connecté."))
        else:
            self.al_state.setText(tr("Le suivi AniList n'est pas disponible dans cette version "
                                     "de Beheread."))
        self.al_login.setVisible(not connected)
        self.al_login.setEnabled(configured)
        self.al_logout.setVisible(connected)
        self.tracking.setEnabled(connected)

    def _anilist_login(self):
        dlg = AniListLoginDialog(self.store, self)
        dlg.exec()
        self._refresh_anilist()

    def _anilist_logout(self):
        if self._confirm(tr("Se déconnecter d'AniList"),
                         tr("Oublier l'accès AniList enregistré sur ce PC ?")):
            self.store.set_anilist_login(None, None)
            self._refresh_anilist()

    # ----- caches -----
    def _clear_thumbs(self):
        if self._confirm(tr("Vider le cache des vignettes"),
                         tr("Supprimer les vignettes en cache ? Elles seront recréées "
                            "à l'affichage.")):
            n = self.actions["clear_thumbs"]()
            self.status.setText(trn(n, "{n} vignette supprimée.", "{n} vignettes supprimées."))

    def _clear_meta(self):
        if self._confirm(tr("Oublier les métadonnées téléchargées"),
                         tr("Oublier les auteurs et dates obtenus en ligne ? Les "
                            "informations issues de ComicInfo.xml ou saisies à la main "
                            "sont conservées.")):
            n = self.actions["clear_meta"]()
            self.status.setText(trn(n, "{n} entrée de métadonnées oubliée.",
                                    "{n} entrées de métadonnées oubliées."))

    def save(self):
        """Ecrit les preferences choisies (appele par la bibliotheque apres
        acceptation du dialogue)."""
        s = self.store
        s.set_ui_pref("theme", self.theme.currentData())
        s.set_ui_pref("language", self.language.currentData())
        # None = couleur d'origine (elle suivrait un changement de la valeur par defaut)
        s.set_ui_pref("accent", None if self._accent == theme.DEFAULT_ACCENT else self._accent)
        s.set_library_pref("view_mode", self.view_mode.currentData())
        s.set_library_pref("group_series", self.group_series.isChecked())
        s.set_library_pref("show_continue", self.show_continue.isChecked())
        s.set_library_pref("show_details", self.show_details.isChecked())
        s.set_library_pref("show_missing", self.show_missing.isChecked())
        s.set_library_pref("show_covered_chapters", self.show_covered.isChecked())
        s.set_reader_pref("manga_mode", bool(self.direction.currentData()))
        s.set_reader_pref("fit_mode", int(self.fit.currentData()))
        s.set_reader_pref("double_page", self.double_page.isChecked())
        s.set_reader_pref("ambilight", self.ambilight.isChecked())
        s.set_reader_pref("page_fade", self.page_fade.isChecked())
        s.set_reader_pref("boss_key", self.boss_key.isChecked())
        s.set_reader_pref("babelio_button", self.babelio.isChecked())
        s.set_ui_pref("global_hotkey", self.global_hotkey.isChecked())
        s.set_ui_pref("check_updates", self.check_updates.isChecked())
        # mots d'origine : rien d'enregistre (ils suivront une evolution de la liste)
        s.set_library_pref("extra_page_words",
                           None if tuple(self._extra_words) == archive.DEFAULT_EXTRA_PAGE_WORDS
                           else list(self._extra_words))
        s.set_anilist_value("tracking", self.tracking.isChecked())
        self._save_servers()
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
        self.setWindowTitle(tr("Connexion à AniList"))
        self.setMinimumWidth(440)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        self.message = QLabel(tr("Autorisez Beheread dans la page AniList qui vient de s'ouvrir "
                                 "dans votre navigateur…"))
        # raison d'echec transmise par le navigateur : non fiable (voir ui/safe_text.py)
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        v.addWidget(self.message)
        row = QHBoxLayout()
        self.reopen = QPushButton(tr("Rouvrir la page"))
        self.reopen.clicked.connect(self._open_browser)
        cancel = QPushButton(tr("Annuler"))
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
        self._viewer_call = None   # verification du compte en cours (CallWorker)
        self._finished = False     # fenetre fermee (voir done)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(lambda: self._on_failed(tr("Délai dépassé.")))
        QTimer.singleShot(0, self._start)

    def _start(self):
        try:
            self.receiver.start()
        except OSError:
            self._fail_hard(tr("Le port local {port} est déjà utilisé par une autre "
                               "application : fermez-la puis réessayez.",
                               port=config.ANILIST_REDIRECT_PORT))
            return
        self._timeout.start(self.TIMEOUT_MS)
        self._open_browser()

    def _open_browser(self):
        QDesktopServices.openUrl(QUrl(anilist.authorize_url(config.anilist_client_id())))

    def _on_token(self, token):
        self._timeout.stop()
        self.message.setText(tr("Vérification du compte…"))
        # requete hors du thread UI : l'interface ne gele pas pendant l'attente
        self._viewer_call = CallWorker(lambda: anilist.viewer(token))
        self._viewer_call.signals.done.connect(
            lambda user, err: self._on_viewer(token, user, err))
        QThreadPool.globalInstance().start(self._viewer_call)

    def _on_viewer(self, token, user, err):
        self._viewer_call = None
        if self._finished:
            return   # fenetre fermee pendant la verification
        if err is not None:
            self._fail_hard(tr("AniList n'a pas validé la connexion :\n{error}", error=err))
            return
        # confirmation explicite du compte : pendant l'attente, n'importe quel
        # site ouvert dans le navigateur peut ouvrir la page locale avec SON
        # jeton (la page le transmet alors elle-meme, avec la bonne origine) ;
        # sans ce garde-fou, la progression de lecture partirait sur son compte
        name = user.get("name") or "?"
        if not self._confirm_account(name):
            self._fail_hard(tr("Connexion annulée : ce n'est pas votre compte AniList."))
            return
        self.store.set_anilist_login(token, name)
        self.accept()

    def _confirm_account(self, name) -> bool:
        return QMessageBox.question(
            self, tr("Connexion à AniList"),
            plain(tr("Connecter Beheread au compte AniList « {name} » ?\n\n"
                     "Si ce n'est pas votre compte, répondez Non.", name=name)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def _on_failed(self, reason):
        self._fail_hard(tr("Connexion non aboutie ({reason}).", reason=reason))

    def _fail_hard(self, text):
        self.receiver.stop()
        self._timeout.stop()
        self.message.setText(text)
        self.reopen.hide()

    def done(self, result):
        self._finished = True
        self.receiver.stop()
        self._timeout.stop()
        super().done(result)


# ---------------------------------------------------------------- saisie manuelle

class EditInfoDialog(QDialog):
    """Saisie manuelle de l'auteur et de l'annee d'un tome ou d'une serie
    (source « manual » : prioritaire, et conservee par les nettoyages)."""

    def __init__(self, heading, author, year, colors, parent=None, published=None):
        """`published` : pour une serie, le nombre de tomes parus saisi a la
        main (0 = automatique) ; None pour un tome (champ absent)."""
        super().__init__(parent)
        self.setWindowTitle(tr("Modifier les informations"))
        self.setMinimumWidth(420)
        self.setStyleSheet(_dialog_css(colors))
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        title = QLabel(heading)
        title.setTextFormat(Qt.PlainText)   # nom de tome ou de serie
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(title)
        f = QFormLayout()
        self.author = QLineEdit(author or "")
        self.author.setPlaceholderText(tr("Inconnu"))
        f.addRow(tr("Auteur"), self.author)
        self.year = QSpinBox()
        self.year.setRange(0, 2100)
        self.year.setSpecialValueText(tr("Inconnue"))
        self.year.setValue(int(year or 0))
        f.addRow(tr("Année de sortie"), self.year)
        self.published = None
        if published is not None:
            self.published = QSpinBox()
            self.published.setRange(0, 999)
            self.published.setSpecialValueText(tr("Automatique"))
            self.published.setValue(int(published or 0))
            self.published.setToolTip(tr("Pour une édition au découpage différent (Perfect, "
                                         "double…) : le nombre trouvé en ligne est celui de "
                                         "l'édition courante"))
            f.addRow(tr("Tomes parus dans votre édition"), self.published)
        root.addLayout(f)
        root.addSpacing(8)
        root.addLayout(_buttons_row(self, tr("Enregistrer")))

    def values(self):
        """(auteurs, annee) saisis : liste vide / None si laisses vides."""
        author = self.author.text().strip()
        return ([author] if author else []), (self.year.value() or None)


# ---------------------------------------------------------------- tome illisible

def explain_archive_error(message: str) -> str:
    """Raison probable, en clair, d'une erreur d'ouverture d'archive."""
    m = (message or "").lower()

    def has(*fragments):   # fragments des messages d'ArchiveError, en francais ou traduits
        return any(f in m or tr(f).lower() in m for f in fragments)

    if has(N_("aucun outil")):
        return (tr("Ce fichier est une vraie archive RAR : il faut un outil de "
                   "décompression pour l'ouvrir.") + " " + tr(platforms.RAR_HELP))
    if has(N_("mot de passe")):
        return tr("Ce PDF est protégé par un mot de passe : Beheread ne peut pas l'ouvrir.")
    if has(N_("aucune image"), N_("aucune page")):
        return tr("Ce fichier ne contient aucune page à afficher.")
    if has(N_("volumineuse")):
        return tr("Une page de ce fichier est anormalement volumineuse : elle a été ignorée par sécurité.")
    if has(N_("zip invalide"), "rar", N_("non reconnu"), N_("illisible")):
        return (tr("Le fichier est probablement incomplet (téléchargement interrompu) ou "
                   "abîmé. Le télécharger à nouveau règle en général le problème."))
    return tr("Beheread n'a pas pu lire ce fichier.")


class UnreadableDialog(QDialog):
    """Detail d'un tome dont la couverture n'a pas pu etre lue."""

    RETRY, REVEAL = 2, 3

    def __init__(self, title, path, message, colors, parent=None):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle(tr("Tome illisible"))
        self.setMinimumWidth(560)
        self.setStyleSheet(_dialog_css(colors) + f"""
            QLabel#detail {{
                color: {colors['text']}; background: {colors['panel']};
                border: 1px solid {colors['border']}; border-radius: 6px; padding: 8px 10px;
                font-family: Consolas, 'Cascadia Mono', Menlo, monospace; font-size: 12px;
            }}""")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(icons.warning(colors["warning"]).pixmap(20, 20))
        head.addWidget(icon, 0, Qt.AlignTop)
        heading = QLabel(tr("« {title} » ne peut pas être ouvert", title=title))
        heading.setTextFormat(Qt.PlainText)   # nom de fichier : non fiable
        heading.setWordWrap(True)
        heading.setStyleSheet("font-size: 15px; font-weight: 700;")
        head.addWidget(heading, 1)
        root.addLayout(head)
        reason = QLabel(explain_archive_error(message))
        reason.setTextFormat(Qt.PlainText)
        reason.setWordWrap(True)
        root.addWidget(reason)
        detail_text = message if str(path) in message else f"{path}\n{message}"
        detail = QLabel(detail_text)
        detail.setObjectName("detail")
        detail.setTextFormat(Qt.PlainText)
        detail.setWordWrap(True)
        detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(detail)
        row = QHBoxLayout()
        reveal = QPushButton(tr(platforms.REVEAL_LABEL))
        reveal.clicked.connect(lambda: self._finish(self.REVEAL))
        retry = QPushButton(tr("Réessayer"))
        retry.clicked.connect(lambda: self._finish(self.RETRY))
        close = QPushButton(tr("Fermer"))
        close.setObjectName("primary")
        close.setDefault(True)
        close.clicked.connect(self.reject)
        row.addWidget(reveal)
        row.addWidget(retry)
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)

    def _finish(self, choice):
        self.choice = choice
        self.done(choice)


# ---------------------------------------------------------------- couverture

class _OfficialCover(QFrame):
    """Encadre « Couverture officielle » de CoverDialog : apercu, source, et
    selection au clic."""

    clicked = Signal()

    def mousePressEvent(self, event):
        if self.isEnabled():
            self.clicked.emit()
        super().mousePressEvent(event)


class CoverDialog(QDialog):
    """Choix de la couverture d'un tome : sa couverture officielle (si
    `official` est donne), une de ses pages (chargees en arriere-plan), ou
    une image de l'ordinateur. `choice` apres acceptation : ("page", index)
    ou ("image", QImage).

    `official` : (fetch, source) - fetch() renvoie l'image (octets) de la
    couverture officielle, ou b"" ; appele hors du thread UI. `source` :
    « Tome 23 · MangaDex »."""

    THUMB = QSize(90, 128)
    OFFICIAL = QSize(96, 136)

    def __init__(self, title, path, current_page, colors, parent=None, official=None):
        super().__init__(parent)
        self.choice = None
        self._official_image = None
        self.setWindowTitle(tr("Choisir la couverture"))
        self.setMinimumSize(660, 520)
        self.setStyleSheet(_dialog_css(colors) + f"""
            QListWidget {{ background: {colors['panel']}; border: 1px solid {colors['border']};
                           border-radius: 6px; color: {colors['text_dim']}; }}
            QListWidget::item:selected {{ background: transparent; color: {colors['text']};
                                          border: 2px solid {theme.ACCENT}; border-radius: 4px; }}
            QFrame#official {{ background: {colors['panel']}; border: 2px solid {colors['border']};
                               border-radius: 8px; }}
            QFrame#official[selected="true"] {{ border-color: {theme.ACCENT}; }}
            QLabel#officialPreview {{ background: {colors['cover_placeholder']};
                                      border-radius: 4px; }}""")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        heading = QLabel(tr("Couverture de « {title} »", title=title))
        heading.setTextFormat(Qt.PlainText)   # nom de fichier : non fiable
        heading.setWordWrap(True)
        heading.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(heading)
        root.addWidget(self._hint(
            tr("La couverture officielle, une page du tome, ou une image de votre ordinateur. "
               "Le fichier n'est pas modifié.") if official is not None
            else tr("Choisissez une page du tome, ou une image de votre "
                    "ordinateur. Le fichier du tome n'est pas modifié.")))
        self.official = None
        if official is not None:
            root.addWidget(self._build_official(official[1]))
            heading_pages = QLabel(tr("Pages du tome"))
            heading_pages.setStyleSheet("font-weight: 600;")
            root.addWidget(heading_pages)
        self.pages = QListWidget()
        self.pages.setViewMode(QListWidget.IconMode)
        self.pages.setIconSize(self.THUMB)
        self.pages.setGridSize(QSize(self.THUMB.width() + 18, self.THUMB.height() + 30))
        self.pages.setMovement(QListWidget.Static)
        self.pages.setResizeMode(QListWidget.Adjust)
        self.pages.setUniformItemSizes(True)
        self.pages.setAccessibleName(tr("Pages du tome"))
        self.pages.currentRowChanged.connect(self._on_page_selected)
        self.pages.itemDoubleClicked.connect(lambda _it: self._use_page())
        root.addWidget(self.pages, 1)
        root.addWidget(self._hint("Faites défiler pour voir les pages suivantes."))
        row = QHBoxLayout()
        image = QPushButton(tr("Image de l'ordinateur…"))
        image.clicked.connect(self._pick_image)
        reset = QPushButton(tr("Revenir à la première page"))
        reset.clicked.connect(self._reset)
        cancel = QPushButton(tr("Annuler"))
        cancel.clicked.connect(self.reject)
        self.use = QPushButton(tr("Utiliser cette page"))
        self.use.setObjectName("primary")
        self.use.setDefault(True)
        self.use.setEnabled(False)
        self.use.clicked.connect(self._use_selected)
        row.addWidget(image)
        row.addWidget(reset)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(self.use)
        root.addLayout(row)

        self._current = current_page
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._loader = PagesWorker(path, self.THUMB.height() * 2)
        self._loader.signals.page.connect(self._on_page)
        self._pool.start(self._loader)
        if official is not None:
            # couverture officielle : telechargee en arriere-plan
            self._official_call = CallWorker(official[0])
            self._official_call.signals.done.connect(self._on_official)
            QThreadPool.globalInstance().start(self._official_call)

    # ----- couverture officielle -----
    def _build_official(self, source):
        frame = _OfficialCover()
        frame.setObjectName("official")
        frame.setCursor(Qt.PointingHandCursor)
        frame.setEnabled(False)   # jusqu'a l'arrivee de l'image
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(16)
        self.official_preview = QLabel()
        self.official_preview.setObjectName("officialPreview")
        self.official_preview.setFixedSize(self.OFFICIAL)
        self.official_preview.setAlignment(Qt.AlignCenter)
        row.addWidget(self.official_preview)
        texts = QVBoxLayout()
        texts.setSpacing(6)
        name = QLabel(tr("Couverture officielle"))
        name.setStyleSheet("font-size: 14px; font-weight: 600;")
        texts.addWidget(name)
        self.official_status = self._hint(tr("Recherche de la couverture officielle…"))
        self.official_source = source
        texts.addWidget(self.official_status)
        texts.addStretch(1)
        row.addLayout(texts, 1)
        frame.clicked.connect(self._select_official)
        self.official = frame
        return frame

    def _on_official(self, data, err):
        image = QImage.fromData(data) if data else QImage()
        if image.isNull():
            self.official_status.setText(
                tr("Couverture officielle introuvable : {error}", error=err) if err is not None
                else tr("MangaDex n'a pas de couverture pour ce tome."))
            return
        self._official_image = image
        pm = QPixmap.fromImage(image).scaled(self.OFFICIAL * self.devicePixelRatioF(),
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(self.devicePixelRatioF())
        self.official_preview.setPixmap(pm)
        self.official_status.setText(self.official_source)
        self.official.setEnabled(True)
        self._select_official()

    def _select_official(self, selected=True):
        if self.official is None or (selected and self._official_image is None):
            return
        self.official.setProperty("selected", "true" if selected else "false")
        self.official.style().unpolish(self.official)
        self.official.style().polish(self.official)
        if selected:
            self.pages.blockSignals(True)
            self.pages.clearSelection()
            self.pages.setCurrentRow(-1)
            self.pages.blockSignals(False)
            self.use.setEnabled(True)
            self.use.setText(tr("Utiliser la couverture officielle"))

    def _official_selected(self):
        return self.official is not None and self.official.property("selected") == "true"

    def _use_selected(self):
        if self._official_selected():
            self.choice = ("image", self._official_image)
            self.accept()
        else:
            self._use_page()

    @staticmethod
    def _hint(text):
        label = QLabel(text)
        label.setObjectName("hint")
        label.setWordWrap(True)
        return label

    def _on_page(self, index, image):
        item = QListWidgetItem(str(index + 1))
        item.setTextAlignment(Qt.AlignHCenter)
        if not image.isNull():
            pm = QPixmap.fromImage(image).scaled(self.THUMB * self.devicePixelRatioF(),
                                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(self.devicePixelRatioF())
            icon = QIcon(pm)
            icon.addPixmap(pm, QIcon.Selected)   # page choisie : bordure, sans teinte
            item.setIcon(icon)
        self.pages.addItem(item)
        if index == self._current and not self._official_selected():
            self.pages.setCurrentItem(item)

    def _on_page_selected(self, row):
        if row >= 0:
            self._select_official(False)
        elif self._official_selected():
            return
        self.use.setEnabled(row >= 0)
        self.use.setText(tr("Utiliser la page {n}", n=row + 1) if row >= 0
                         else tr("Utiliser cette page"))

    def _use_page(self):
        if self.pages.currentRow() >= 0:
            self.choice = ("page", self.pages.currentRow())
            self.accept()

    def _reset(self):
        self.choice = ("page", 0)
        self.accept()

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Image de couverture"), str(Path.home()),
                                              tr("Images (*.jpg *.jpeg *.png *.webp *.bmp *.gif)"))
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, tr("Image illisible"),
                                tr("Cette image n'a pas pu être lue. Choisissez un fichier JPEG, "
                                   "PNG ou WebP."))
            return
        limit = 268 * config.THUMB_SCALE * 2   # largement assez net pour une vignette
        if image.height() > limit:
            image = image.scaledToHeight(limit, Qt.SmoothTransformation)
        self.choice = ("image", image)
        self.accept()

    def done(self, result):
        self._loader.cancel()
        self._pool.clear()
        self._pool.waitForDone(2000)
        super().done(result)
