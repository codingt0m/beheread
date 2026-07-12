"""Bibliotheque : grille (ou liste) de vignettes des mangas trouves dans les
dossiers sources, avec recherche, tri, filtres de statut, regroupement par
serie et actions (suppression, reinitialisation, marquage lu) sur simple ou
multiple selection. Les couvertures sont generees en arriere-plan et mises
en cache sur disque."""

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QFileSystemWatcher, QSize, Qt,
                            QThreadPool, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QIcon, QImage, QKeySequence, QPixmap, QShortcut)
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QMessageBox, QScrollArea, QSizePolicy,
                               QSlider, QToolButton, QVBoxLayout, QWidget)

import metadata
import theme
from archive_handler import Archive
from series import normalize_name, parse_series, parse_series_ex
from storage import Store

# modules extraits (voir chacun) : constantes de rendu, delegates, dialogues et
# taches d'arriere-plan. LibraryWidget (ci-dessous) orchestre le tout.
from lib_constants import (GRID_GAP, ROLE_AUTHOR_TEXT,
                           ROLE_FINISHED, ROLE_FRACTION, ROLE_IS_HEADER,
                           ROLE_IS_SERIES, ROLE_PATH, ROLE_PIXMAP,
                           ROLE_PIXMAP2, ROLE_PIXMAP3, ROLE_PROG_TEXT,
                           ROLE_SERIES_COUNT, ROLE_SERIES_KEY,
                           ROLE_SERIES_PATHS, THUMB_H, THUMB_SCALE, THUMB_W)
from lib_delegates import ListDelegate, MangaDelegate
from lib_dialogs import FolderManagerDialog
from version import __version__
from lib_workers import (MetaWorker, ScanWorker, SeriesMetaWorker, ThumbWorker)
import icons


class SmoothListWidget(QListWidget):
    """QListWidget dont la molette defile d'un pas fixe en pixels, avec une
    courte animation pour lisser le mouvement. Sans ca, un cran de molette
    avance de 3 x le pas du scrollbar, que QListView cale sur la hauteur des
    cases : en vue grille (cases de ~350 px) chaque cran saute d'un kilometre.
    Les trackpads (pixelDelta) gardent le defilement natif."""

    WHEEL_STEP = 110   # pixels par cran de molette

    backRequested = Signal()   # Echap / Retour arriere : remonter d'un niveau

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wheel_anim = QVariantAnimation(self)
        self._wheel_anim.setDuration(140)
        self._wheel_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._wheel_anim.valueChanged.connect(
            lambda v: self.verticalScrollBar().setValue(int(v)))

    def wheelEvent(self, event):
        if not event.pixelDelta().isNull():
            super().wheelEvent(event)
            return
        sb = self.verticalScrollBar()
        steps = event.angleDelta().y() / 120.0
        # si une animation est en cours, on enchaine depuis sa cible pour que
        # les crans rapides s'accumulent au lieu de repartir de la position
        # courante (ce qui "avalerait" une partie du defilement)
        if self._wheel_anim.state() == QVariantAnimation.Running:
            base = self._wheel_anim.endValue()
        else:
            base = sb.value()
        target = max(sb.minimum(),
                     min(sb.maximum(), base - steps * self.WHEEL_STEP))
        self._wheel_anim.stop()
        # les deux bornes doivent etre du meme type : QVariantAnimation ne
        # sait pas interpoler entre un int et un float (elle n'emet alors
        # aucune valeur et le scroll semble mort)
        self._wheel_anim.setStartValue(float(sb.value()))
        self._wheel_anim.setEndValue(float(target))
        self._wheel_anim.start()
        event.accept()

    def keyPressEvent(self, event):
        # Echap ou Retour arriere : remonter d'un niveau (sortir d'un dossier
        # de serie). Sans effet au niveau racine (gere par le widget parent).
        if event.key() in (Qt.Key_Escape, Qt.Key_Backspace):
            self.backRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # bouton lateral "page precedente" de la souris : meme retour qu'Echap
        if event.button() == Qt.BackButton:
            self.backRequested.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._center_grid()

    def _center_grid(self):
        """Centre la grille (vue IconMode) : QListView aligne les cases a
        gauche et laisse toute la place restante a droite. On replie cette
        place en deux marges de viewport egales de part et d'autre.

        Cle de la stabilite : la vue utilise setGridSize (voir
        LibraryWidget._apply_view_mode), donc le nombre de colonnes vaut
        EXACTEMENT viewport_width // gridWidth. Le calcul ci-dessous est alors
        un point fixe :

          available = largeur utile hors marges (reconstruite en rajoutant les
                      marges actuelles a la largeur de viewport - grandeur
                      STABLE, independante des marges qu'on va poser, et qui
                      tient deja compte du cadre et de la barre de defilement) ;
          cols      = available // gridWidth ;
          extra     = available - cols*gridWidth  (reparti en marges egales).

        Apres pose des marges, viewport_width == cols*gridWidth, donc la vue
        affiche exactement `cols` colonnes sans trou a droite, et un nouvel
        appel recalcule les memes marges (aucun ping-pong). Sans setGridSize,
        le critere de colonne de QListView n'est pas ce simple quotient et ce
        point fixe n'existe pas - c'etait la cause des essais precedents
        instables (grille collabee sur une colonne, ou marges asymetriques)."""
        if self.viewMode() != QListWidget.IconMode:
            return
        grid_w = self.gridSize().width()
        if grid_w <= 0:
            return
        m = self.viewportMargins()
        available = self.viewport().width() + m.left() + m.right()
        # QListView (mesure a l'usage) affiche N colonnes seulement si la
        # largeur de viewport est STRICTEMENT superieure a N*gridWidth (un
        # ajustement pile a N*gridWidth retombe a N-1, laissant un trou d'une
        # case). On garde donc 1px de mou DANS le viewport apres la derniere
        # case, et on repartit le reste en marges egales de part et d'autre.
        cols = max(1, (available - 1) // grid_w)
        slack = available - cols * grid_w    # >= 1
        if slack < 1:
            left = right = 0
        else:
            left = slack // 2
            right = slack - left - 1          # le 1px restant tient dans le viewport
        if (left, right) != (m.left(), m.right()):
            self.setViewportMargins(left, 0, right, 0)


class _ClickableContainer(QWidget):
    """QWidget generique qui emet clicked() sur un clic gauche - utilise pour
    rendre le logo/titre "BEHEREAD" cliquable sans en changer l'apparence."""
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


# ---------------------------------------------------------------- widget

class LibraryWidget(QWidget):
    mangaActivated = Signal(str)
    themeToggleRequested = Signal()

    # bornes du curseur de taille des couvertures (pourcentage de la taille de
    # reference). Le maximum est cale sur la resolution du cache de vignettes
    # (THUMB_SCALE fois la taille de reference) pour rester net meme sur un
    # ecran haute densite : au-dela, on afficherait plus grand que le cache.
    GRID_SCALE_MIN = 60
    GRID_SCALE_MAX = 100 * THUMB_SCALE // 2   # 150% (cache 3x, ecran jusqu'a 2x)

    @classmethod
    def _clamp_scale(cls, pct: int) -> int:
        return max(cls.GRID_SCALE_MIN, min(cls.GRID_SCALE_MAX, pct))

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.pool = QThreadPool.globalInstance()
        self._thumb_workers = {}        # path -> worker en vol (libere a la fin)

        self._entries = []              # dicts : path, title, series, volume, added
        self._thumb_cache = {}          # path -> QPixmap (persiste entre les filtrages)
        self._thumb_pending = set()
        self._path_to_item = {}         # path -> QListWidgetItem (tome, acces O(1))
        # chemins de couverture -> items qui l'affichent (tome OU dossier de
        # serie qui empile cette couverture) : mis a jour a l'arrivee du thumb
        self._cover_subscribers = {}
        # chemin -> dossiers de serie interesses par ses metadonnees (auteur)
        self._meta_subscribers = {}
        # serie ouverte (drill-in) : None au niveau racine, sinon cle de serie
        self._current_series = None
        self._series_display_name = {}   # cle normalisee -> nom affiche (vote)
        self._entry_by_path = {}         # path -> entree (acces O(1))

        # metadonnees auteur/date (ComicInfo.xml -> Google Books -> AniList) :
        # pool dedie et limite a 1 thread pour rester poli avec les API distantes
        self.meta_pool = QThreadPool()
        self.meta_pool.setMaxThreadCount(1)
        self._meta_workers = {}         # path -> worker en vol (libere a la fin)
        self._meta_pending = set()
        self._meta_failed_session = set()   # echecs reseau : pas retente avant redemarrage

        # recherche AniList au niveau serie (auteur pour tous les tomes d'un
        # coup) : pool distinct (autre hote qu'un tome Google Books) pour que
        # l'auteur apparaisse vite, en parallele des recherches par tome
        self.series_meta_pool = QThreadPool()
        self.series_meta_pool.setMaxThreadCount(1)
        self._series_meta_workers = {}      # cle serie -> worker en vol
        self._series_meta_pending = set()
        self._series_meta_failed_session = set()

        # scan des dossiers en arriere-plan (non bloquant)
        self._scanning = False
        self._scan_again = False
        self._scan_worker = None

        self._search_text = ""
        self._group_series = bool(store.library_pref("group_series", False))
        self._view_mode = store.library_pref("view_mode", "grid")
        # taille des couvertures en vue grille (pourcentage, cf. curseur du
        # header et MangaDelegate.set_scale) ; borne haute alignee sur la
        # resolution du cache de vignettes pour rester net (voir GRID_SCALE_MAX)
        self._grid_scale_pct = self._clamp_scale(
            int(store.library_pref("grid_scale_pct", 100)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        QShortcut(QKeySequence("F5"), self, self.refresh)
        QShortcut(QKeySequence.Find, self, self.search_edit.setFocus)   # Ctrl+F

        self.list = SmoothListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setWordWrap(True)
        # necessaire pour que le defilement au pixel de SmoothListWidget ne
        # soit pas re-aligne sur les cases par la vue
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setHorizontalScrollMode(QListWidget.ScrollPerPixel)
        self.list.itemActivated.connect(self._on_activated)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list)

        self.grid_delegate = MangaDelegate(self.store, self.list)
        self.grid_delegate.set_scale(self._grid_scale_pct / 100.0)
        self.list_delegate = ListDelegate(self.store, self.list)
        self._apply_view_mode()

        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_label)

        self.apply_theme()

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._rebuild_list)

        # surveillance automatique des dossiers sources : un CBZ/CBR ajoute ou
        # retire declenche un rafraichissement (debounce), sans F5 manuel
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_source_dir_changed)
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(800)
        self._watch_timer.timeout.connect(self.refresh)

        self.list.backRequested.connect(self._exit_series)

        # offline-first : affiche l'instantane persiste immediatement, puis
        # lance le scan reel en arriere-plan pour reconcilier
        self._load_persisted_index()
        self.refresh()
        self.list.setFocus()

    # ----- header -----
    def _icon_button(self, tooltip, checkable=False):
        btn = QToolButton()
        btn.setObjectName("headerBtn")
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(34, 34)
        btn.setIconSize(QSize(18, 18))
        btn.setCheckable(checkable)
        btn.setFocusPolicy(Qt.NoFocus)
        return btn

    def _build_header(self):
        self.header = QWidget()
        self.header.setObjectName("headerBar")
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(16, 8, 12, 8)
        hl.setSpacing(6)

        # -- identite : logo + titre, cliquable pour revenir a la racine de
        # la bibliotheque (quitte un dossier de serie et/ou une recherche)
        self.home_btn = _ClickableContainer()
        self.home_btn.setCursor(Qt.PointingHandCursor)
        self.home_btn.setToolTip(f"Retour a la bibliotheque   -   Beheread v{__version__}")
        self.home_btn.clicked.connect(self._go_home)
        home_layout = QHBoxLayout(self.home_btn)
        home_layout.setContentsMargins(0, 0, 0, 0)
        home_layout.setSpacing(6)

        self.logo_label = QLabel()
        icon_path = Path(__file__).resolve().parent / "icon.ico"
        if icon_path.exists():
            self.logo_label.setPixmap(QIcon(str(icon_path)).pixmap(QSize(28, 28)))
        self.title_label = QLabel()
        self.title_label.setObjectName("appTitle")
        self.title_label.setTextFormat(Qt.RichText)
        home_layout.addWidget(self.logo_label)
        home_layout.addWidget(self.title_label)
        hl.addWidget(self.home_btn)

        # -- fil d'Ariane : bouton retour, visible seulement dans un dossier
        self.btn_back = QToolButton()
        self.btn_back.setObjectName("backBtn")
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.setFocusPolicy(Qt.NoFocus)
        self.btn_back.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_back.clicked.connect(self._exit_series)
        self.btn_back.hide()
        hl.addSpacing(6)
        hl.addWidget(self.btn_back)

        hl.addStretch(1)

        # -- recherche, mise en valeur au centre
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("searchEdit")
        self.search_edit.setPlaceholderText("Rechercher un titre ou un auteur...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedSize(300, 32)
        self.search_edit.textChanged.connect(self._on_search_changed)
        self._search_icon_action = self.search_edit.addAction(
            icons.search("#808080"), QLineEdit.LeadingPosition)
        hl.addWidget(self.search_edit)

        hl.addStretch(1)

        # -- curseur de taille des couvertures (vue grille)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setObjectName("sizeSlider")
        self.size_slider.setFixedWidth(96)
        self.size_slider.setMinimum(self.GRID_SCALE_MIN)
        self.size_slider.setMaximum(self.GRID_SCALE_MAX)
        self.size_slider.setValue(self._grid_scale_pct)
        self.size_slider.setToolTip("Taille des couvertures")
        self.size_slider.setFocusPolicy(Qt.NoFocus)
        self.size_slider.valueChanged.connect(self._on_grid_scale_changed)
        hl.addWidget(self.size_slider)

        hl.addWidget(self._header_separator())

        self.btn_group = self._icon_button("Regrouper par serie", checkable=True)
        self.btn_group.setChecked(self._group_series)
        self.btn_group.toggled.connect(self._on_group_toggled)
        hl.addWidget(self.btn_group)

        self.btn_view = self._icon_button("")
        self.btn_view.clicked.connect(self._on_view_toggled)
        hl.addWidget(self.btn_view)

        hl.addWidget(self._header_separator())

        # -- gestion des dossiers (un seul bouton -> panneau facon Plex)
        self.btn_folders = self._icon_button("Gérer les dossiers sources")
        self.btn_folders.clicked.connect(self.manage_folders)
        hl.addWidget(self.btn_folders)

        self.btn_refresh = self._icon_button("Rafraichir  (F5)")
        self.btn_refresh.clicked.connect(self.refresh)
        hl.addWidget(self.btn_refresh)

        hl.addWidget(self._header_separator())

        # -- theme clair/sombre
        self.btn_theme = self._icon_button("")
        self.btn_theme.clicked.connect(self.themeToggleRequested.emit)
        hl.addWidget(self.btn_theme)

        return self.header

    def _header_separator(self):
        sep = QFrame()
        sep.setObjectName("headerSep")
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedHeight(22)
        return sep

    # ----- theme -----
    def apply_theme(self):
        mode = self.store.ui_pref("theme", "dark")
        c = theme.colors(mode)
        self.list.setStyleSheet(
            f"QListWidget {{ background: {c['list_bg']}; border: none; }}")
        self.empty_label.setStyleSheet(f"color: {c['text_dim']}; font-size: 14px;")

        self.header.setStyleSheet(f"""
            #headerBar {{
                background: {c['panel']};
                border-bottom: 1px solid {c['border']};
            }}
            #appTitle {{
                font-size: 22px;
                font-weight: 800;
                letter-spacing: 1.5px;
                padding-left: 4px;
            }}
            QToolButton#headerBtn {{
                background: transparent;
                border: none;
                border-radius: 8px;
            }}
            QToolButton#headerBtn:hover {{
                background: {c['button_hover']};
            }}
            QToolButton#headerBtn:checked {{
                background: rgba(192, 57, 43, 55);
            }}
            QToolButton#backBtn {{
                color: {c['text']};
                background: transparent;
                border: 1px solid {c['border']};
                border-radius: 15px;
                padding: 4px 12px 4px 8px;
                font-size: 13px;
                font-weight: 600;
            }}
            QToolButton#backBtn:hover {{
                background: {c['button']};
                border-color: {c['text_dim']};
            }}
            QLineEdit#searchEdit {{
                color: {c['text']};
                background: {c['list_bg']};
                border: 1px solid {c['border']};
                border-radius: 16px;
                padding: 0 12px;
            }}
            QLineEdit#searchEdit:focus {{
                border-color: {theme.ACCENT};
            }}
            #headerSep {{
                color: {c['border']};
                margin: 0 4px;
            }}
            QSlider#sizeSlider::groove:horizontal {{
                height: 4px;
                background: {c['border']};
                border-radius: 2px;
            }}
            QSlider#sizeSlider::sub-page:horizontal {{
                background: {theme.ACCENT};
                border-radius: 2px;
            }}
            QSlider#sizeSlider::handle:horizontal {{
                width: 12px;
                height: 12px;
                margin: -5px 0;
                border-radius: 6px;
                background: {c['text']};
            }}
            QSlider#sizeSlider::handle:horizontal:hover {{
                background: {theme.ACCENT};
            }}
        """)

        # titre bicolore : "BEHE" en accent, "READ" dans la couleur du texte
        self.title_label.setText(
            f'<span style="color:{theme.ACCENT}">BEHE</span>'
            f'<span style="color:{c["text"]}">READ</span>')

        # re-teinte des icones dans la couleur du theme courant
        ic = c["text"]
        self.btn_folders.setIcon(icons.folder_cog(ic))
        self.btn_refresh.setIcon(icons.refresh(ic))
        self.btn_group.setIcon(icons.layers(theme.ACCENT if self._group_series else ic))
        self._search_icon_action.setIcon(icons.search(c["text_dim"]))
        # convention : l'icone montre le mode/la vue vers lesquels on bascule
        self.btn_theme.setIcon(icons.sun(ic) if mode == "dark" else icons.moon(ic))
        self.btn_theme.setToolTip("Passer au theme clair" if mode == "dark"
                                  else "Passer au theme sombre")
        self.btn_back.setIcon(icons.chevron_left(ic))
        self._update_view_button()

        self.list.viewport().update()

    # ----- vue grille / liste -----
    def _grid_cell_size(self) -> QSize:
        """Taille d'une case de grille (couverture + legende + jeu inter-case).
        Le jeu (GRID_GAP) est integre a la case et setSpacing vaut 0 : le
        nombre de colonnes est alors exactement viewport_width // gridWidth,
        condition d'un centrage stable (cf. SmoothListWidget._center_grid)."""
        d = self.grid_delegate
        return QSize(d.cell_w + GRID_GAP, d.cell_h + GRID_GAP)

    def _apply_view_mode(self):
        if self._view_mode == "list":
            self.list.setViewMode(QListWidget.ListMode)
            self.list.setFlow(QListWidget.TopToBottom)
            self.list.setWrapping(False)
            self.list.setUniformItemSizes(False)
            self.list.setSpacing(1)
            self.list.setGridSize(QSize())   # desactive la grille fixe
            self.list.setItemDelegate(self.list_delegate)
            self.list.setViewportMargins(0, 0, 0, 0)   # pas de centrage hors vue grille
        else:
            self.list.setViewMode(QListWidget.IconMode)
            self.list.setFlow(QListWidget.LeftToRight)
            self.list.setWrapping(True)
            self.list.setResizeMode(QListWidget.Adjust)
            self.list.setMovement(QListWidget.Static)
            self.list.setUniformItemSizes(True)
            self.list.setSpacing(0)
            self.list.setGridSize(self._grid_cell_size())
            self.list.setItemDelegate(self.grid_delegate)
            self.list._center_grid()

    def _update_view_button(self):
        c = theme.colors(self.store.ui_pref("theme", "dark"))
        if self._view_mode == "grid":
            self.btn_view.setIcon(icons.list_view(c["text"]))
            self.btn_view.setToolTip("Passer en vue liste")
        else:
            self.btn_view.setIcon(icons.grid(c["text"]))
            self.btn_view.setToolTip("Passer en vue grille")

    def _on_view_toggled(self):
        self._view_mode = "list" if self._view_mode == "grid" else "grid"
        self.store.set_library_pref("view_mode", self._view_mode)
        self._apply_view_mode()
        self._update_view_button()
        self._rebuild_list()

    def _on_grid_scale_changed(self, pct: int):
        """Curseur de taille : ajuste l'echelle des couvertures. Les vignettes
        en cache sont haute resolution et remises a l'echelle au dessin (voir
        MangaDelegate), donc rien a recharger - il suffit de repasser la
        nouvelle taille de case a la vue et de recentrer."""
        self._grid_scale_pct = self._clamp_scale(pct)
        self.store.set_library_pref("grid_scale_pct", self._grid_scale_pct)
        self.grid_delegate.set_scale(self._grid_scale_pct / 100.0)
        if self._view_mode == "grid":
            self.list.setGridSize(self._grid_cell_size())
            self.list._center_grid()
            self.list.viewport().update()

    def _on_group_toggled(self, checked):
        self._group_series = checked
        self.store.set_library_pref("group_series", checked)
        self._current_series = None   # quitter un eventuel dossier ouvert
        c = theme.colors(self.store.ui_pref("theme", "dark"))
        self.btn_group.setIcon(icons.layers(theme.ACCENT if checked else c["text"]))
        self.btn_group.setToolTip("Regrouper par serie (dossiers)")
        self._rebuild_list()

    # ----- actions dossiers -----
    def manage_folders(self):
        """Ouvre le panneau de gestion des dossiers sources (facon Plex) :
        liste des dossiers avec nombre de mangas, ajout par navigation et
        retrait individuel. Les modifications ne sont appliquees qu'a la
        validation."""
        mode = self.store.ui_pref("theme", "dark")
        dlg = FolderManagerDialog(self.store.folders(), theme.colors(mode), self)
        if dlg.exec() == QDialog.Accepted:
            new_folders = dlg.result_folders()
            if new_folders != self.store.folders():
                self.store.set_folders(new_folders)
                self.refresh()

    def _dedupe_by_content(self, paths):
        """Deux fichiers identiques (meme contenu - copie du meme tome dans
        un autre dossier source, ou doublon au meme endroit) ne doivent
        apparaitre qu'une seule fois dans la bibliotheque. La progression,
        les metadonnees et la vignette sont deja partagees par empreinte de
        contenu (voir Store.key_for) : il suffit ici de ne garder qu'un seul
        chemin representant par empreinte, choisi de facon stable (ordre
        alphabetique) pour que ce ne soit jamais le meme fichier qui
        "disparaisse" arbitrairement d'un rafraichissement a l'autre."""
        kept_path_for_key = {}
        result = []
        for p in sorted(paths):
            key = self.store.key_for(p)
            if key not in kept_path_for_key:
                kept_path_for_key[key] = p
                result.append(p)
        return result

    def _dedupe_by_series_volume(self, entries):
        """Deux fichiers *differents* (releases distinctes, scans differents -
        pas detectes par _dedupe_by_content qui ne voit que le contenu
        identique) peuvent neanmoins etre le meme tome de la meme serie
        (ex. "Berserk Volume 42" et "Berserk_T42"). On ne garde alors qu'un
        seul representant par (serie normalisee, numero de tome), en
        privilegiant celui qui reflete le mieux la lecture en cours -
        termine, puis entame, puis a defaut le premier par ordre alphabetique
        (stable). Les tomes sans numero detectable (one-shots, titres
        isoles) ne sont jamais fusionnes entre eux : leur seule identite
        fiable est le nom de fichier exact."""
        groups = {}
        singles = []
        for e in entries:
            if e["volume"] is None:
                singles.append(e)
                continue
            # la NATURE du numero fait partie de la cle : un chapitre et un tome
            # de meme numero (ou un numero nu, d'identite fragile) sont des
            # contenus distincts a ne pas fusionner - seuls de vrais doublons de
            # tome relie ("Berserk Volume 42" et "Berserk_T42") se rejoignent.
            key = (normalize_name(e["series"]), e.get("kind"), e["volume"])
            groups.setdefault(key, []).append(e)

        def read_rank(e):
            prog = self.store.get_progress(e["path"])
            if prog and prog[2]:
                return 2   # termine
            if prog and prog[0] > 0:
                return 1   # entame
            return 0

        result = list(singles)
        for group in groups.values():
            if len(group) == 1:
                result.append(group[0])
            else:
                result.append(min(group, key=lambda e: (-read_rank(e), e["path"])))
        return result

    # ----- scan + (re)construction de la liste -----
    def refresh(self):
        """Relance un scan des dossiers sources en arriere-plan (non bloquant).
        Coalesce les demandes rapprochees : un scan deja en cours n'est pas
        double, une nouvelle demande le relance a sa fin."""
        if self._scanning:
            self._scan_again = True
            return
        self._scanning = True
        self._scan_again = False
        worker = ScanWorker(self.store, self.store.folders())
        worker.signals.done.connect(self._on_scan_done)
        self._scan_worker = worker   # garde une reference (sinon GC)
        self.pool.start(worker)

    def _on_scan_done(self, paths):
        self._scanning = False
        self._scan_worker = None
        self._apply_scan_results(paths)
        # une demande de rescan est arrivee pendant celui-ci : on la traite
        if self._scan_again:
            self.refresh()

    def _apply_scan_results(self, paths):
        """Finalise un scan (cote UI) : construit les entrees a partir des
        chemins dedupliques, persiste l'index, met a jour la surveillance et
        reconstruit la liste. Les empreintes ayant deja ete calculees par le
        worker, key_for/series_override ne touchent ici que le cache."""
        added = self.store.ensure_added(paths)
        entries = []
        for p in paths:
            stem = Path(p).stem
            sname, svolume, skind = parse_series_ex(stem)
            # regroupement : un tome peut etre detache de tout regroupement
            # automatique (clic droit)
            override = self.store.series_override(p)
            detached = False
            if override == Store.SERIES_DETACHED:
                detached = True
            elif override:
                sname = override
            entries.append({"path": p, "title": stem, "series": sname,
                            "volume": svolume, "kind": skind,
                            "added": added.get(p, 0), "detached": detached})
        entries = self._dedupe_by_series_volume(entries)
        self._set_entries(entries)
        self.store.save_library_index(entries)
        # scan reel termine : purge les vignettes/empreintes orphelines (fichiers
        # supprimes ou sortis des dossiers sources depuis le dernier scan). Base
        # sur `paths` (tous les contenus distincts presents), pas sur `entries`
        # (deja fusionnees par serie/tome), pour ne pas purger le cache d'une
        # release deduplifiee mais toujours sur le disque.
        try:
            self.store.purge_orphan_caches(paths)
        except Exception:
            logging.warning("Purge des caches orphelins en echec", exc_info=True)
        self._update_watches()
        self._rebuild_list()

    def _set_entries(self, entries):
        self._entries = entries
        self._entry_by_path = {e["path"]: e for e in entries}

    def _load_persisted_index(self):
        """Affiche immediatement le dernier instantane connu de la bibliotheque
        (offline-first) : la fenetre est consultable des le demarrage, sans
        attendre le scan disque (qui reconcilie ensuite en arriere-plan). Les
        fichiers disparus depuis seront retires a la fin du scan."""
        index = self.store.load_library_index()
        entries = [e for e in index
                   if isinstance(e, dict) and e.get("path") and "title" in e]
        if entries:
            self._set_entries(entries)
            self._rebuild_list()

    def update_progress_display(self):
        """Rafraichit l'affichage (progression, tri) au retour du lecteur."""
        self._rebuild_list()

    # ----- surveillance des dossiers sources -----
    def _update_watches(self):
        """(Re)installe la surveillance sur chaque dossier source et ses
        sous-dossiers. QFileSystemWatcher n'est pas recursif : on enumere donc
        l'arborescence, avec un plafond pour ne pas saturer sur des racines
        gigantesques."""
        try:
            current = self._watcher.directories()
            if current:
                self._watcher.removePaths(current)
            dirs = []
            seen = set()
            for folder in self.store.folders():
                if not os.path.isdir(folder):
                    continue
                for root, subdirs, _files in os.walk(folder):
                    if root not in seen:
                        seen.add(root)
                        dirs.append(root)
                    if len(dirs) >= 2000:
                        break
                if len(dirs) >= 2000:
                    break
            if dirs:
                self._watcher.addPaths(dirs)
        except Exception:
            # non bloquant : le rafraichissement automatique sera juste
            # indisponible, le bouton "Rafraichir" reste un filet de secours.
            logging.warning("Echec de la surveillance des dossiers sources", exc_info=True)

    def _on_source_dir_changed(self, _path):
        # coalesce plusieurs evenements rapproches (copie de plusieurs fichiers)
        self._watch_timer.start()

    def _authors_text(self, e):
        """Auteur(s) connus pour ce fichier (cache local uniquement, ne
        declenche pas de recherche) - utilise pour la recherche texte.
        Repli sur l'auteur de la serie (AniList) si le tome n'a pas le sien."""
        meta = self.store.volume_meta(e["path"])
        if meta and not meta.get("not_found") and meta.get("authors"):
            return ", ".join(meta["authors"])
        return self._series_author_text(normalize_name(e["series"]))

    def _series_author_text(self, series_key):
        """Auteur en cache au niveau de la serie (AniList), ou ""."""
        sm = self.store.series_meta(series_key)
        if sm and not sm.get("not_found") and sm.get("authors"):
            return ", ".join(sm["authors"])
        return ""

    def _ensure_series_author(self, series_key, series_name):
        """Declenche une recherche AniList au niveau serie (une fois) pour
        renseigner l'auteur de tous ses tomes rapidement. Sans effet si la
        serie a deja des metadonnees en cache (a jour) ou une recherche en
        cours. Un cache "not_found" ecrit par une cascade plus ancienne (avant
        l'ajout d'une source comme MangaDex) est traite comme absent, pour
        retenter automatiquement une fois la nouvelle source disponible."""
        cached = self.store.series_meta(series_key)
        if cached is not None and not metadata.is_stale_not_found(cached):
            return
        if (series_key in self._series_meta_pending
                or series_key in self._series_meta_failed_session):
            return
        self._series_meta_pending.add(series_key)
        worker = SeriesMetaWorker(series_key, series_name)
        worker.signals.done.connect(self._on_series_meta_done)
        self._series_meta_workers[series_key] = worker
        self.series_meta_pool.start(worker)

    def _on_series_meta_done(self, series_key, series_data, ok):
        self._series_meta_pending.discard(series_key)
        self._series_meta_workers.pop(series_key, None)
        if ok and series_data is not None:
            self.store.set_series_meta(series_key, series_data)
        else:
            self._series_meta_failed_session.add(series_key)
        # rafraichit l'auteur affiche de tous les items de cette serie (les
        # tomes sans auteur propre et le dossier de serie) sans reconstruire
        for path, item in self._path_to_item.items():
            e = self._entry_by_path.get(path)
            if e is not None and normalize_name(e["series"]) == series_key:
                self._update_item_meta(path)
        self.list.viewport().update()

    # ----- metadonnees auteur/date (ComicInfo.xml -> Google Books -> AniList) -----
    def _get_or_fetch_meta(self, e):
        """Renvoie les metadonnees en cache pour ce fichier (ou None si pas
        encore connues), et declenche une recherche en arriere-plan si
        necessaire. Les entrees sans metadonnees se trient en fin de liste
        et se replacent d'elles-memes des que la recherche (asynchrone,
        cascade ComicInfo/Google Books/AniList) aboutit."""
        path = e["path"]
        cached = self.store.volume_meta(path)
        if cached is not None and not metadata.is_stale_not_found(cached):
            return None if cached.get("not_found") else cached
        # recherche serie eager : l'auteur apparait vite pour tous les tomes
        self._ensure_series_author(normalize_name(e["series"]), e["series"])
        if path not in self._meta_pending and path not in self._meta_failed_session:
            self._meta_pending.add(path)
            cached_series = self.store.series_meta(normalize_name(e["series"]))
            if cached_series is not None and metadata.is_stale_not_found(cached_series):
                cached_series = None   # perime : forcer une nouvelle recherche
            worker = MetaWorker(path, e["series"], e["volume"], cached_series)
            worker.signals.done.connect(self._on_meta_done)
            self._meta_workers[path] = worker
            self.meta_pool.start(worker)
        return None

    def _on_meta_done(self, path, data, series_data, ok):
        self._meta_pending.discard(path)
        self._meta_workers.pop(path, None)   # worker termine : reference liberee
        # cle de serie recalculee depuis l'entree correspondante (le worker ne
        # la renvoie pas pour eviter de dupliquer l'etat) :
        e = self._entry_by_path.get(path)
        if e is not None and series_data is not None:
            self.store.set_series_meta(normalize_name(e["series"]), series_data)
        if ok:
            self.store.set_volume_meta(path, data if data else metadata.not_found_sentinel())
        else:
            self._meta_failed_session.add(path)

        # la metadonnee arrive en continu pour toute la bibliotheque en
        # arriere-plan ; l'ordre affiche n'en depend jamais (pas de tri par
        # auteur/date dans l'UI), donc une simple mise a jour de l'item
        # suffit - pas besoin de reconstruire toute la liste (couteux).
        self._update_item_meta(path)

    def _meta_tooltip_and_author(self, path, meta):
        author_text = ""
        extra = []
        if meta and not meta.get("not_found"):
            if meta.get("authors"):
                author_text = ", ".join(meta["authors"])
                extra.append("Auteur : " + author_text)
            if meta.get("published_year"):
                extra.append(f"Date de sortie : {meta['published_year']}"
                            f" (source : {meta.get('source', '?')})")
        if not author_text:
            # repli sur l'auteur de la serie (recherche AniList au niveau serie)
            e = self._entry_by_path.get(path)
            if e is not None:
                author_text = self._series_author_text(normalize_name(e["series"]))
                if author_text:
                    extra.insert(0, "Auteur : " + author_text)
        est = self._time_estimate_text(path)
        if est:
            extra.append(est)
        tooltip = path if not extra else path + "\n\n" + "\n".join(extra)
        return tooltip, author_text

    def _time_estimate_text(self, path):
        """Estimation du temps de lecture (restant si le tome est entame, total
        sinon), basee sur le rythme personnel mesure et le nombre de pages
        connu. Renvoie "" tant que le rythme n'a pas ete mesure ou que le
        nombre de pages est inconnu."""
        pace = self.store.median_page_seconds()
        if not pace:
            return ""
        prog = self.store.get_progress(path)
        total = (prog[1] if prog and prog[1] else None) or self.store.page_count(path)
        if not total:
            return ""
        if prog and prog[2]:
            return ""   # termine : rien a estimer
        read = prog[0] if prog else 0
        remaining_pages = max(0, total - read)
        minutes = pace * remaining_pages / 60.0
        if minutes < 1:
            label = "moins d'une minute"
        elif minutes < 60:
            label = f"~{int(round(minutes))} min"
        else:
            label = f"~{int(minutes // 60)} h {int(round(minutes % 60)):02d}"
        prefix = "Temps restant" if (prog and read > 0) else "Temps de lecture"
        return f"{prefix} : {label}"

    def _update_item_meta(self, path):
        """Met a jour l'auteur/tooltip d'un seul item deja affiche, sans
        reconstruire toute la liste (voir _on_meta_done)."""
        meta = self.store.volume_meta(path)
        tooltip, author_text = self._meta_tooltip_and_author(path, meta)
        item = self._path_to_item.get(path)
        if item is not None:
            item.setData(ROLE_AUTHOR_TEXT, author_text)
            item.setToolTip(tooltip)
        if author_text:
            # dossiers de serie abonnes a ce tome : leur auteur vient d'arriver
            for sitem in self._meta_subscribers.get(path, ()):
                sitem.setData(ROLE_AUTHOR_TEXT, author_text)
        self.list.viewport().update()

    def _compute_display_names(self, entries):
        """Une meme serie peut avoir des noms de fichiers formates differemment
        (ex. "Gloutons & Dragons" vs "gloutons-dragons") : ils partagent la
        meme cle normalisee, mais on affiche le nom le plus frequent du groupe
        plutot qu'une variante au hasard."""
        name_votes = {}
        for e in entries:
            if e.get("detached"):
                continue
            key = normalize_name(e["series"])
            votes = name_votes.setdefault(key, {})
            votes[e["series"]] = votes.get(e["series"], 0) + 1
        return {key: max(votes.items(), key=lambda kv: kv[1])[0]
                for key, votes in name_votes.items()}

    def _rebuild_list(self):
        self.list.clear()
        self._path_to_item = {}   # reconstruit avec la liste (acces O(1) ensuite)
        self._cover_subscribers = {}
        self._meta_subscribers = {}
        entries = self._entries

        q = self._search_text.strip().casefold()
        self._series_display_name = self._compute_display_names(self._entries)

        # une recherche pioche a plat dans tous les tomes (elle "traverse" les
        # dossiers) ; sinon, si le regroupement est actif, on affiche des
        # dossiers de serie (et le contenu d'un dossier ouvert).
        grouping = self._group_series and not q
        if grouping and self._current_series is not None:
            self._rebuild_series_contents(entries)
            self._update_empty_state(self.list.count() > 0, searching=False)
        elif grouping:
            self._rebuild_series_folders(entries)
            self._update_empty_state(self.list.count() > 0, searching=False)
        else:
            # vue a plat : on ajoute TOUS les tomes une fois, puis on masque en
            # place ceux qui ne correspondent pas a la recherche (voir
            # _apply_row_filter). Les frappes suivantes ne reconstruisent donc
            # plus toute la liste - le filtrage est instantane.
            self._current_series = None
            for e in sorted(self._entries, key=lambda e: e["title"].casefold()):
                self._add_item(e)
            self._apply_row_filter()

        self._update_back_button()
        self.list._center_grid()

    def _on_search_changed(self, text):
        prev = self._search_text
        self._search_text = text
        if self._can_filter_in_place(prev, text):
            # meme jeu d'items affiche (vue a plat) : filtrage instantane par
            # masquage de lignes, sans reconstruction ni debounce.
            self._search_timer.stop()
            self._apply_row_filter()
        else:
            # changement structurel (dossiers <-> plat, sortie d'une serie) :
            # reconstruction debouncee
            self._search_timer.start()

    def _can_filter_in_place(self, prev, cur):
        """Le filtrage en place n'est possible que si le jeu d'items affiche ne
        change pas : vue a plat (regroupement desactive), ou recherche deja
        active qui le reste (regroupement actif). Sinon il faut reconstruire."""
        if self._current_series is not None:
            return False
        if not self._group_series:
            return True
        return bool(prev.strip()) and bool(cur.strip())

    def _apply_row_filter(self):
        """Masque/affiche chaque ligne selon la recherche courante (titre, serie
        ou auteur), sans reconstruire la liste."""
        q = self._search_text.strip().casefold()
        any_visible = False
        for i in range(self.list.count()):
            item = self.list.item(i)
            e = self._entry_by_path.get(item.data(ROLE_PATH))
            match = (not q) or (e is not None and (
                q in e["title"].casefold() or q in e["series"].casefold()
                or q in self._authors_text(e).casefold()))
            self.list.setRowHidden(i, not match)
            any_visible = any_visible or match
        self._update_empty_state(has_any_result=any_visible, searching=bool(q))

    def _update_empty_state(self, has_any_result, searching):
        self.list.setVisible(has_any_result)
        self.empty_label.setVisible(not has_any_result)
        if not self._entries:
            self.empty_label.setText(
                "Bibliotheque vide.\n\nCliquez sur \"Ajouter un dossier\" pour choisir "
                "un repertoire contenant vos fichiers CBZ / CBR / EPUB.")
        elif not has_any_result:
            self.empty_label.setText("Aucun manga ne correspond a la recherche."
                                     if searching else "Aucun manga a afficher.")

    def _group_entries(self, entries):
        """Regroupe les tomes par cle de serie normalisee. Les tomes detaches
        manuellement (clic droit) sont exclus du regroupement : ils restent
        des tomes isoles."""
        groups = {}
        for e in entries:
            if e.get("detached"):
                continue
            groups.setdefault(normalize_name(e["series"]), []).append(e)
        return groups

    def _rebuild_series_folders(self, entries):
        """Niveau racine du mode regroupe : un dossier par serie multi-tomes,
        les series a un seul tome (et les tomes detaches) affichees comme un
        tome normal. Series et tomes isoles sont intercales par ordre
        alphabetique."""
        groups = self._group_entries(entries)
        renderables = []   # (nom de tri, "item"|"series", charge utile)
        for key, grp in groups.items():
            if len(grp) == 1:
                renderables.append((grp[0]["title"].casefold(), "item", grp[0]))
            else:
                name = self._series_display_name.get(key, grp[0]["series"])
                renderables.append((name.casefold(), "series", (key, grp)))
        for e in entries:
            if e.get("detached"):
                renderables.append((e["title"].casefold(), "item", e))
        for _, kind, payload in sorted(renderables, key=lambda r: r[0]):
            if kind == "item":
                self._add_item(payload)
            else:
                self._add_series_item(*payload)

    def _rebuild_series_contents(self, entries):
        """Contenu d'un dossier de serie ouvert : ses tomes, tries par numero."""
        grp = self._group_entries(entries).get(self._current_series)
        if not grp:
            # la serie a disparu (fichiers retires) : on remonte au niveau racine
            self._current_series = None
            self._rebuild_series_folders(entries)
            return
        for e in sorted(grp, key=self._volume_sort_key):
            self._add_item(e)

    def _volume_sort_key(self, e):
        return (e["volume"] if e["volume"] is not None else -1, e["title"].casefold())

    def _add_item(self, e):
        item = QListWidgetItem(e["title"])
        item.setData(ROLE_PATH, e["path"])
        # declenche (ou reutilise) la recherche de metadonnees pour toute la
        # bibliotheque, pas seulement quand on trie par auteur/date : l'info
        # se remplit progressivement en arriere-plan des l'affichage, sans
        # reconstruire la liste a chaque reponse (voir _on_meta_done).
        meta = self._get_or_fetch_meta(e)
        tooltip, author_text = self._meta_tooltip_and_author(e["path"], meta)
        item.setData(ROLE_AUTHOR_TEXT, author_text)
        item.setToolTip(tooltip)
        self._apply_progress(item, e["path"])
        self.list.addItem(item)
        self._path_to_item[e["path"]] = item
        self._bind_cover(item, e["path"], ROLE_PIXMAP)

    def _series_featured_index(self, vols):
        """Indice (dans `vols`, tries par numero) du tome a mettre en tete de
        pile d'un dossier de serie : le tome en cours de lecture (prioritaire),
        sinon celui qui suit le dernier tome termine - c'est le prochain a
        lire - ou le dernier termine lui-meme s'il clot la serie, sinon le
        premier tome."""
        in_progress = None
        last_finished = None
        for i, e in enumerate(vols):
            prog = self.store.get_progress(e["path"])
            if not prog:
                continue
            if prog[2]:
                last_finished = i
            else:
                in_progress = i   # garde le plus avance (liste triee par numero)
        if in_progress is not None:
            return in_progress
        if last_finished is not None:
            return min(last_finished + 1, len(vols) - 1)
        return 0

    def _series_author(self, vols):
        """Auteur(s) connus pour la serie : premiere metadonnee en cache parmi
        ses tomes (aucune recherche declenchee ici)."""
        for e in vols:
            meta = self.store.volume_meta(e["path"])
            if meta and not meta.get("not_found") and meta.get("authors"):
                return ", ".join(meta["authors"])
        return ""

    def _add_series_item(self, key, group):
        display = self._series_display_name.get(key, group[0]["series"])
        item = QListWidgetItem(display)
        item.setData(ROLE_IS_SERIES, True)
        item.setData(ROLE_SERIES_KEY, key)
        item.setData(ROLE_SERIES_COUNT, len(group))

        # tete de pile : le tome pertinent (en cours / prochain a lire), les
        # couches arriere montrant les tomes qui le suivent
        vols = sorted(group, key=self._volume_sort_key)
        f = self._series_featured_index(vols)
        rotated = vols[f:] + vols[:f]
        cover_paths = [v["path"] for v in rotated[:3]]
        item.setData(ROLE_SERIES_PATHS, cover_paths)

        read, count, frac, finished = self._series_progress(group)
        item.setData(ROLE_FRACTION, frac)
        item.setData(ROLE_FINISHED, finished)
        if finished:
            item.setData(ROLE_PROG_TEXT, "Serie terminee")
        elif read > 0:
            item.setData(ROLE_PROG_TEXT, f"{read}/{count} tomes lus")
        else:
            item.setData(ROLE_PROG_TEXT, f"{count} tomes")

        # auteur : depuis le cache des tomes ; la recherche est declenchee pour
        # le tome vedette et l'item s'abonne au resultat (voir _update_item_meta)
        self._get_or_fetch_meta(rotated[0])
        author = self._series_author(vols)
        item.setData(ROLE_AUTHOR_TEXT, author)
        self._meta_subscribers.setdefault(rotated[0]["path"], []).append(item)

        tooltip = f"{display}  ·  {count} tomes"
        if author:
            tooltip += f"\nAuteur : {author}"
        item.setToolTip(tooltip)

        self.list.addItem(item)
        for role, path in zip((ROLE_PIXMAP, ROLE_PIXMAP2, ROLE_PIXMAP3), cover_paths):
            self._bind_cover(item, path, role)

    def _series_progress(self, group):
        """Agrege la progression d'une serie : nombre de tomes termines,
        total, fraction lue, et si toute la serie est terminee."""
        count = len(group)
        read = 0
        for e in group:
            prog = self.store.get_progress(e["path"])
            if prog and prog[2]:
                read += 1
        frac = read / count if count else 0.0
        return read, count, frac, (read == count and count > 0)

    def _bind_cover(self, item, path, role):
        """Associe la couverture de `path` a `item` (au role donne) : depuis le
        cache si dispo, sinon abonne l'item et declenche le chargement."""
        pm = self._thumb_cache.get(path)
        if pm is not None:
            item.setData(role, pm)
            return
        self._cover_subscribers.setdefault(path, []).append(item)
        self._request_thumb(path)

    # ----- navigation dans les dossiers de serie -----
    def _enter_series(self, key):
        self._current_series = key
        self._rebuild_list()
        self.list.scrollToTop()
        self.list.setFocus()

    def _exit_series(self):
        if self._current_series is None:
            return
        self._current_series = None
        self._rebuild_list()
        self.list.setFocus()

    def _go_home(self):
        """Clic sur le logo "BEHEREAD" : retour a la racine de la
        bibliotheque - quitte un dossier de serie ouvert et efface une
        recherche en cours, comme un logo de site ramene a l'accueil."""
        changed = self._current_series is not None or bool(self._search_text)
        self._current_series = None
        if self._search_text:
            self._search_timer.stop()
            self.search_edit.blockSignals(True)
            self.search_edit.clear()
            self.search_edit.blockSignals(False)
            self._search_text = ""
        if changed:
            self._rebuild_list()
        self.list.setFocus()

    def _update_back_button(self):
        if self._current_series is not None:
            name = self._series_display_name.get(self._current_series, "Serie")
            self.btn_back.setText(name)
            self.btn_back.setToolTip("Retour a la bibliotheque  (Echap)")
            self.btn_back.show()
        else:
            self.btn_back.hide()

    # ----- interne -----
    def _apply_progress(self, item: QListWidgetItem, path: str):
        prog = self.store.get_progress(path)
        if prog:
            page, total, finished = prog
            frac = (page + 1) / total if total else 0.0
            item.setData(ROLE_FRACTION, min(1.0, frac))
            item.setData(ROLE_FINISHED, finished)
            if total:
                txt = "Termine" if finished else f"Page {page + 1} / {total}"
                item.setData(ROLE_PROG_TEXT, txt)
        else:
            item.setData(ROLE_FRACTION, 0.0)
            item.setData(ROLE_FINISHED, False)
            item.setData(ROLE_PROG_TEXT, "")

    def _request_thumb(self, path: str):
        if path in self._thumb_pending:
            return
        self._thumb_pending.add(path)
        worker = ThumbWorker(path, self.store.thumb_path(path))
        worker.signals.done.connect(self._on_thumb_done)
        worker.signals.failed.connect(self._on_thumb_failed)
        worker.signals.count.connect(self.store.set_page_count)
        self._thumb_workers[path] = worker  # garde une reference aux signaux
        self.pool.start(worker)

    def _on_thumb_done(self, path: str, image: QImage):
        # On memorise UNE couverture haute resolution (recadree au rapport de
        # reference THUMB_W:THUMB_H), a la resolution du cache disque
        # (THUMB_SCALE x la taille de reference). Le delegate la remet a
        # l'echelle de la case courante au dessin : la meme vignette sert donc
        # a toutes les tailles du curseur, en restant nette (jamais agrandie
        # au-dela du cache, cf. GRID_SCALE_MAX), sans rien recharger quand la
        # taille change.
        target = QSize(THUMB_W * THUMB_SCALE, THUMB_H * THUMB_SCALE)
        raw = QPixmap.fromImage(image)
        pm = raw.scaled(target, Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation)
        # KeepAspectRatioByExpanding peut deborder d'un cote : on rogne au centre
        # pour obtenir exactement `target` (rapport de reference constant).
        if pm.width() > target.width() or pm.height() > target.height():
            x = max(0, (pm.width() - target.width()) // 2)
            y = max(0, (pm.height() - target.height()) // 2)
            pm = pm.copy(x, y, min(target.width(), pm.width()),
                         min(target.height(), pm.height()))
        self._thumb_cache[path] = pm
        self._thumb_pending.discard(path)
        self._thumb_workers.pop(path, None)   # worker termine : reference liberee
        # met a jour tous les items qui affichent cette couverture : le tome
        # lui-meme et/ou les dossiers de serie qui l'empilent (chacun au bon
        # role de couche - front / 2e / 3e couverture)
        for item in self._cover_subscribers.get(path, ()):
            self._apply_cover_to_item(item, path, pm)
        self.list.viewport().update()

    def _apply_cover_to_item(self, item, path, pm):
        if item.data(ROLE_IS_SERIES):
            cover_paths = item.data(ROLE_SERIES_PATHS) or []
            for role, p in zip((ROLE_PIXMAP, ROLE_PIXMAP2, ROLE_PIXMAP3), cover_paths):
                if p == path:
                    item.setData(role, pm)
        else:
            item.setData(ROLE_PIXMAP, pm)

    def _on_thumb_failed(self, path: str, message: str):
        # La vignette reste grise ; l'erreur detaillee apparaitra a l'ouverture.
        self._thumb_pending.discard(path)
        self._thumb_workers.pop(path, None)

    def _on_activated(self, item: QListWidgetItem):
        if item.data(ROLE_IS_HEADER):
            return
        if item.data(ROLE_IS_SERIES):
            self._enter_series(item.data(ROLE_SERIES_KEY))
            return
        self.mangaActivated.emit(item.data(ROLE_PATH))

    # ----- menu contextuel (clic droit), simple ou multi-selection -----
    def _show_context_menu(self, pos):
        item = self.list.itemAt(pos)
        # les dossiers de serie (et en-tetes) n'ont pas d'actions par tome :
        # on entre dedans pour agir sur un tome precis
        if item is None or item.data(ROLE_IS_HEADER) or item.data(ROLE_IS_SERIES):
            return
        if item not in self.list.selectedItems():
            self.list.clearSelection()
            item.setSelected(True)
            self.list.setCurrentItem(item)

        items = [it for it in self.list.selectedItems()
                 if not it.data(ROLE_IS_HEADER) and not it.data(ROLE_IS_SERIES)]
        if not items:
            return
        n = len(items)

        menu = QMenu(self)
        act_reset = menu.addAction(
            "Reinitialiser la progression" if n == 1 else f"Reinitialiser la progression ({n})")
        act_finished = menu.addAction(
            "Marquer comme lu" if n == 1 else f"Marquer {n} mangas comme lus")
        # "Marquer comme non lu" : annule un marquage "termine" (accidentel ou
        # non) sans perdre la page courante - propose seulement si au moins un
        # tome selectionne est effectivement marque termine.
        paths = [it.data(ROLE_PATH) for it in items]
        act_unread = None
        if any((self.store.get_progress(p) or (0, 0, False))[2] for p in paths):
            act_unread = menu.addAction(
                "Marquer comme non lu" if n == 1 else f"Marquer {n} mangas comme non lus")
        menu.addSeparator()
        act_reload_meta = menu.addAction(
            "Recharger les metadonnees" if n == 1 else f"Recharger les metadonnees ({n})")
        act_rename = menu.addAction("Renommer le fichier...") if n == 1 else None
        act_explorer = menu.addAction("Afficher dans l'explorateur") if n == 1 else None

        # --- regroupement en serie ---
        act_detach = act_restore = None
        if any(self._is_grouped_in_series(p) for p in paths):
            menu.addSeparator()
            act_detach = menu.addAction(
                "Sortir de la serie" if n == 1 else f"Sortir {n} mangas de leur serie")
        if any(self.store.series_override(p) is not None for p in paths):
            if act_detach is None:
                menu.addSeparator()
            act_restore = menu.addAction("Retablir le regroupement automatique")

        menu.addSeparator()
        act_delete = menu.addAction(
            "Supprimer le manga..." if n == 1 else f"Supprimer {n} mangas...")

        chosen = menu.exec(self.list.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_detach:
            for p in paths:
                if self._is_grouped_in_series(p):
                    self.store.set_series_override(p, Store.SERIES_DETACHED)
            self.refresh()
        elif chosen == act_restore:
            for p in paths:
                self.store.clear_series_override(p)
            self.refresh()
        elif chosen == act_reset:
            for it in items:
                self.store.remove_progress(it.data(ROLE_PATH))
            self._rebuild_list()
        elif chosen == act_finished:
            for it in items:
                self._mark_finished(it.data(ROLE_PATH))
            self._rebuild_list()
        elif act_unread is not None and chosen == act_unread:
            for it in items:
                self._mark_unread(it.data(ROLE_PATH))
            self._rebuild_list()
        elif chosen == act_reload_meta:
            self._reload_meta([it.data(ROLE_PATH) for it in items])
        elif act_rename is not None and chosen == act_rename:
            self._rename_tome(items[0].data(ROLE_PATH))
        elif act_explorer is not None and chosen == act_explorer:
            self._show_in_explorer(items[0].data(ROLE_PATH))
        elif chosen == act_delete:
            self._delete_many([it.data(ROLE_PATH) for it in items])

    # ----- regroupement automatique en serie (detachement par clic droit) -----
    def _is_grouped_in_series(self, path):
        """Vrai si ce tome fait actuellement partie d'une serie a plusieurs
        tomes (et n'est donc pas deja isole ou detache)."""
        e = self._entry_by_path.get(path)
        if not e or e.get("detached"):
            return False
        key = normalize_name(e["series"])
        n = sum(1 for x in self._entries
                if not x.get("detached") and normalize_name(x["series"]) == key)
        return n > 1

    # caracteres interdits dans un nom de fichier sous Windows
    _INVALID_NAME_CHARS = set('<>:"/\\|?*')
    # noms de peripheriques reserves par Windows (insensibles a la casse, avec
    # ou sans extension) : un fichier ne peut pas s'appeler ainsi.
    _RESERVED_NAMES = {"con", "prn", "aux", "nul",
                       *(f"com{i}" for i in range(1, 10)),
                       *(f"lpt{i}" for i in range(1, 10))}

    def _rename_tome(self, path: str):
        """Renomme le vrai fichier sur le disque (l'extension est conservee).
        La progression, les metadonnees, la vignette et les regroupements
        manuels sont indexes par contenu : ils suivent le fichier renomme."""
        p = Path(path)
        old_stem = p.stem
        new_stem, ok = QInputDialog.getText(
            self, "Renommer le fichier",
            "Nouveau nom (sans l'extension) :", QLineEdit.Normal, old_stem)
        if not ok:
            return
        new_stem = new_stem.strip().rstrip(" .")   # Windows interdit un nom finissant par espace/point
        if not new_stem or new_stem == old_stem:
            return
        if (self._INVALID_NAME_CHARS & set(new_stem)) or any(ord(c) < 32 for c in new_stem):
            QMessageBox.warning(
                self, "Nom invalide",
                'Un nom de fichier ne peut pas contenir les caracteres :\n'
                '< > : " / \\ | ? *')
            return
        # "CON", "NUL", "COM1"... sont reserves par Windows, meme avec extension
        if new_stem.split(".")[0].lower() in self._RESERVED_NAMES:
            QMessageBox.warning(
                self, "Nom invalide",
                f'"{new_stem}" est un nom reserve par Windows et ne peut pas '
                "etre utilise comme nom de fichier.")
            return

        target = p.with_name(new_stem + p.suffix)
        if target.exists():
            QMessageBox.warning(
                self, "Renommage impossible",
                f'Un fichier nomme "{target.name}" existe deja dans ce dossier.')
            return

        try:
            p.rename(target)
        except OSError as e:
            QMessageBox.warning(
                self, "Renommage impossible",
                f"Impossible de renommer le fichier :\n\n{e}\n\n"
                "Il est peut-etre ouvert dans le lecteur ou une autre application.")
            return

        self.store.note_renamed(str(p), str(target))
        # la vignette en cache (indexee par contenu) reste valide : on la
        # transfere dans le cache memoire vers le nouveau chemin pour eviter un
        # clignotement le temps d'un rechargement.
        if str(p) in self._thumb_cache:
            self._thumb_cache[str(target)] = self._thumb_cache.pop(str(p))
        self.refresh()

    @staticmethod
    def _show_in_explorer(path: str):
        """Ouvre l'explorateur de fichiers avec le fichier selectionne."""
        if sys.platform == "win32":
            # "explorer /select," met le fichier en surbrillance dans son dossier
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _mark_finished(self, path: str):
        prog = self.store.get_progress(path)
        total = prog[1] if prog and prog[1] else None
        if not total:
            try:
                ar = Archive(path)
                total = len(ar)
                ar.close()
            except Exception as e:
                QMessageBox.warning(self, "Erreur",
                                    f"Impossible de lire l'archive :\n{path}\n\n{e}")
                return
        self.store.set_progress(path, max(0, total - 1), total, True)

    def _mark_unread(self, path: str):
        """Annule le marquage "termine" en conservant la page courante (inverse
        d'un "Marquer comme lu" accidentel, sans perdre sa progression)."""
        prog = self.store.get_progress(path)
        if prog and prog[2]:
            self.store.set_progress(path, prog[0], prog[1], False)

    def _reload_meta(self, paths):
        """Oublie les metadonnees (et l'eventuel repli serie AniList associe)
        pour relancer la cascade ComicInfo/Google Books/AniList a zero -
        utile si une recherche precedente n'a rien trouve, s'est trompee, ou
        a echoue faute de reseau au moment ou elle a ete tentee."""
        for p in paths:
            self.store.remove_volume_meta(p)
            self._meta_failed_session.discard(p)
            e = self._entry_by_path.get(p)
            if e is not None:
                self.store.remove_series_meta(normalize_name(e["series"]))
        self._rebuild_list()

    def _delete_many(self, paths):
        # suppression vers la corbeille si send2trash est disponible (repli sur
        # une suppression definitive sinon)
        try:
            from send2trash import send2trash
        except Exception:
            send2trash = None
        to_trash = send2trash is not None

        verb = "Mettre a la corbeille" if to_trash else "Supprimer definitivement"
        if len(paths) == 1:
            title = "Mettre a la corbeille" if to_trash else "Supprimer le manga"
            message = f"{verb} \"{Path(paths[0]).stem}\" ?\n\n{paths[0]}"
        else:
            title = "Mettre a la corbeille" if to_trash else "Supprimer des mangas"
            names = "\n".join(f"- {Path(p).stem}" for p in paths[:10])
            if len(paths) > 10:
                names += f"\n... et {len(paths) - 10} de plus"
            message = f"{verb} {len(paths)} mangas ?\n\n{names}"
        if to_trash:
            message += "\n\nLes fichiers seront envoyes dans la corbeille de Windows."
        else:
            message += "\n\nLes fichiers seront supprimes du disque. Cette action est irreversible."

        confirm = QMessageBox.question(self, title, message,
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return

        deleted, errors = [], []
        for p in paths:
            # l'identite par contenu doit lire le fichier encore present : on
            # resout le chemin de vignette et on purge les donnees liees AVANT
            # de retirer le fichier du disque.
            thumb = self.store.thumb_path(p)
            self.store.remove_progress(p)
            self.store.remove_added(p)
            self.store.remove_volume_meta(p)
            try:
                if to_trash:
                    send2trash(str(Path(p)))
                else:
                    Path(p).unlink()
            except Exception as e:   # send2trash leve ses propres exceptions
                errors.append(f"{Path(p).name} : {e}")
                continue
            deleted.append(p)
            try:
                if thumb.exists():
                    thumb.unlink()
            except OSError:
                pass

        if deleted:
            deleted_set = set(deleted)
            self._entries = [e for e in self._entries if e["path"] not in deleted_set]
            self._thumb_cache = {p: pm for p, pm in self._thumb_cache.items() if p not in deleted_set}
            self._rebuild_list()
        if errors:
            QMessageBox.warning(self, "Erreur",
                                "Certains fichiers n'ont pas pu etre supprimes :\n\n" +
                                "\n".join(errors))
