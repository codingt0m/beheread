"""En-tete, barre d'outils, bandeau de consentement, etat vide, aide et glisser-deposer de la bibliotheque.

Mixin de LibraryWidget : ces methodes partagent l'etat du widget
(self.list, self.store, self._entries...) ; elles sont regroupees ici par
responsabilite pour garder chaque fichier lisible."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from beheread import platforms
from beheread.core import units
from beheread.core.library_model import SORTS, STATUS_FILTERS
from beheread.i18n import tr
from beheread.infra.archive import SUPPORTED_EXTS
from beheread.ui import appicon, icons, keys, theme

# modules extraits (voir chacun) : constantes de rendu, delegates, dialogues et
# taches d'arriere-plan. LibraryWidget (ci-dessous) orchestre le tout.
from beheread.ui.library.constants import CHAPTER_GAP, CHAPTER_SCALE, GRID_GAP
from beheread.ui.library.dialogs import FolderManagerDialog
from beheread.ui.library.views import _ClickableContainer
from beheread.version import __version__


class ChromeMixin:
    # ----- header -----
    def _icon_button(self, label, shortcut="", checkable=False):
        btn = QToolButton()
        btn.setObjectName("headerBtn")
        self._set_button_label(btn, label, shortcut)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(34, 34)
        btn.setIconSize(QSize(18, 18))
        btn.setCheckable(checkable)
        # atteignable a la touche Tab (pas au clic : pas d'anneau de focus
        # parasite a la souris)
        btn.setFocusPolicy(Qt.TabFocus)
        return btn

    @staticmethod
    def _set_button_label(btn, label, shortcut=""):
        """Info-bulle (avec le raccourci) et nom accessible (lu par les
        lecteurs d'ecran : un bouton a icone seule n'a pas de texte)."""
        btn.setToolTip(f"{label}   {keys.label(shortcut)}" if shortcut else label)
        btn.setAccessibleName(label)

    def _build_header(self):
        self.header = QWidget()
        self.header.setObjectName("headerBar")
        root = QHBoxLayout(self.header)
        root.setContentsMargins(16, 8, 16, 8)
        root.setSpacing(6)
        # trois zones : [identite] [recherche] [boutons]. Les deux zones
        # laterales recoivent toujours la meme largeur (voir _balance_header),
        # de sorte que la recherche soit exactement au centre de la fenetre,
        # quel que soit le contenu de chaque cote.
        self._header_left = QWidget()
        hl = QHBoxLayout(self._header_left)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        root.addWidget(self._header_left, 1)

        # -- identite : logo + titre, cliquable pour revenir a la racine de
        # la bibliotheque (quitte un dossier de serie et/ou une recherche)
        self.home_btn = _ClickableContainer()
        self.home_btn.setCursor(Qt.PointingHandCursor)
        self.home_btn.setToolTip(tr("Retour à la bibliothèque") + f"   ·   Beheread v{__version__}")
        self.home_btn.clicked.connect(self._go_home)
        home_layout = QHBoxLayout(self.home_btn)
        home_layout.setContentsMargins(0, 0, 0, 0)
        home_layout.setSpacing(6)

        self.logo_label = QLabel()   # image posee par apply_theme (suit l'accent)
        self.title_label = QLabel()
        self.title_label.setObjectName("appTitle")
        self.title_label.setTextFormat(Qt.RichText)
        home_layout.addWidget(self.logo_label)
        home_layout.addWidget(self.title_label)
        hl.addWidget(self.home_btn)
        # -- source : cet ordinateur ou un serveur de lecture (voir sources.py)
        hl.addSpacing(8)
        hl.addWidget(self._build_source_switch())

        # -- fil d'Ariane : bouton retour, visible seulement dans un dossier
        self.btn_back = QToolButton()
        self.btn_back.setObjectName("backBtn")
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.setFocusPolicy(Qt.TabFocus)
        self.btn_back.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_back.clicked.connect(self._exit_series)
        self.btn_back.hide()
        hl.addSpacing(6)
        hl.addWidget(self.btn_back)
        hl.addStretch(1)

        # -- recherche, exactement au centre
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("searchEdit")
        self.search_edit.setPlaceholderText(tr("Rechercher un titre, une série ou un auteur…"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName(tr("Rechercher dans la bibliothèque"))
        # la police du Mac est un peu plus large : le texte d'invite y tient en 320 px
        self.search_edit.setFixedSize(320 if platforms.IS_MACOS else 300, 32)
        self.search_edit.textChanged.connect(self._on_search_changed)
        self._search_icon_action = self.search_edit.addAction(
            icons.search("#808080"), QLineEdit.LeadingPosition)
        root.addWidget(self.search_edit)

        # -- a droite : l'essentiel seulement. Theme, vue grille/liste,
        # regroupement par serie, panneau d'informations et aide des
        # raccourcis sont dans les preferences.
        self._header_right = QWidget()
        hl = QHBoxLayout(self._header_right)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        root.addWidget(self._header_right, 1)
        hl.addStretch(1)

        # -- curseur de taille des couvertures (vue grille)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setObjectName("sizeSlider")
        self.size_slider.setFixedWidth(96)
        self.size_slider.setMinimum(self.GRID_SCALE_MIN)
        self.size_slider.setMaximum(self.GRID_SCALE_MAX)
        self.size_slider.setValue(self._grid_scale_pct)
        self.size_slider.setToolTip(tr("Taille des couvertures"))
        self.size_slider.setAccessibleName(tr("Taille des couvertures"))
        self.size_slider.setFocusPolicy(Qt.TabFocus)
        self.size_slider.valueChanged.connect(self._on_grid_scale_changed)
        hl.addWidget(self.size_slider)

        hl.addWidget(self._header_separator())

        # -- gestion des dossiers (un seul bouton -> panneau facon Plex)
        self.btn_folders = self._icon_button(tr("Gérer les dossiers sources"))
        self.btn_folders.clicked.connect(self.manage_folders)
        hl.addWidget(self.btn_folders)

        self.btn_refresh = self._icon_button(tr("Rafraîchir"), "F5")
        self.btn_refresh.clicked.connect(self.refresh)
        hl.addWidget(self.btn_refresh)

        hl.addWidget(self._header_separator())

        self.btn_stats = self._icon_button(tr("Statistiques de lecture"))
        self.btn_stats.clicked.connect(self.open_stats)
        hl.addWidget(self.btn_stats)

        self.btn_prefs = self._icon_button(tr("Préférences"), "Ctrl+,")
        self.btn_prefs.clicked.connect(self.open_preferences)
        hl.addWidget(self.btn_prefs)
        if not platforms.IS_MACOS:   # sous macOS : menu Beheread > Reglages (app.py)
            QShortcut(QKeySequence("Ctrl+,"), self, self.open_preferences)

        return self.header

    def _balance_header(self):
        """Donne la meme largeur minimale aux deux cotes de l'en-tete : avec
        le meme facteur d'etirement, ils ont alors toujours la meme largeur
        et la recherche reste au centre. A rappeler quand le contenu d'un
        cote change (bouton de retour, feuille de style)."""
        side = max(self._header_left.sizeHint().width(),
                   self._header_right.sizeHint().width())
        self._header_left.setMinimumWidth(side)
        self._header_right.setMinimumWidth(side)

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
                background: {theme.ACCENT_SOFT};
            }}
            QToolButton#headerBtn:focus {{
                border: 2px solid {theme.ACCENT};
            }}
            QToolButton#backBtn:focus {{
                border: 2px solid {theme.ACCENT};
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
        """ + self.source_switch_css(c, theme.ACCENT))

        # logo et titre bicolore : "BEHE" en accent, "READ" dans la couleur du texte
        self.logo_label.setPixmap(appicon.app_icon().pixmap(QSize(28, 28)))
        self.title_label.setText(
            f'<span style="color:{theme.ACCENT}">BEHE</span>'
            f'<span style="color:{c["text"]}">READ</span>')

        # re-teinte des icones dans la couleur du theme courant
        ic = c["text"]
        self.btn_folders.setIcon(icons.folder(ic))
        self.btn_refresh.setIcon(icons.refresh(ic))
        self._search_icon_action.setIcon(icons.search(c["text_dim"]))
        self.btn_prefs.setIcon(icons.cog(ic))
        self.btn_stats.setIcon(icons.bar_chart(ic))
        self._style_empty_panel(c)
        self._help.apply_colors(c)
        self.shelf.apply_colors(c, theme.ACCENT)
        self.series_band.apply_colors(c)
        self.list.set_fade_color(c['list_bg'])
        self.detail.apply_colors(c)
        self._style_toolbar(c)
        self.btn_back.setIcon(icons.chevron_left(ic))
        self._balance_header()

        self.list.viewport().update()
        self._update_detail()

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
            self.list.setSpacing(0)
            self._apply_grid_layout()
            self.list.setItemDelegate(self.grid_delegate)
            self.list._center_grid()

    def _apply_grid_layout(self):
        """Grille fixe, ou - dossier de serie a sections (tomes, puis
        chapitres en petites cases) - mise en page en flux, ou chaque case
        donne sa taille : les en-tetes de section prennent toute une ligne et
        les petites cases se serrent davantage. Chaque case y porte le jeu
        inter-case que la grille fixe integrait (voir MangaDelegate.flow_gap)."""
        self.grid_delegate.flow_gap = GRID_GAP if self._sectioned else 0
        self.chapter_delegate.flow_gap = CHAPTER_GAP if self._sectioned else 0
        if self._sectioned:
            self.list.setUniformItemSizes(False)
            self.list.flow_column_w = self.grid_delegate.cell_w + GRID_GAP
            self.list.setGridSize(QSize())
            self.list.doItemsLayout()
        else:
            self.list.flow_column_w = 0
            self.list.setUniformItemSizes(True)
            self.list.setGridSize(self._grid_cell_size())

    def _set_view_mode(self, mode):
        """Vue grille ou liste (choisie dans les preferences)."""
        mode = "list" if mode == "list" else "grid"
        if mode != self._view_mode:
            self._view_mode = mode
            self._apply_view_mode()

    def _on_grid_scale_changed(self, pct: int):
        """Curseur de taille : ajuste l'echelle des couvertures. Les vignettes
        en cache sont haute resolution et remises a l'echelle au dessin (voir
        MangaDelegate), donc rien a recharger - il suffit de repasser la
        nouvelle taille de case a la vue et de recentrer."""
        self._grid_scale_pct = self._clamp_scale(pct)
        self.store.set_library_pref("grid_scale_pct", self._grid_scale_pct)
        self.grid_delegate.set_scale(self._grid_scale_pct / 100.0)
        self.chapter_delegate.set_scale(self._grid_scale_pct / 100.0 * CHAPTER_SCALE)
        if self._view_mode == "grid":
            self._apply_grid_layout()
            self.list._center_grid()
            self.list.viewport().update()

    def _set_group_series(self, grouped):
        """Regroupement des tomes en dossiers de serie (choisi dans les
        preferences)."""
        grouped = bool(grouped)
        if grouped != self._group_series:
            self._group_series = grouped
            self._current_series = None   # quitter un eventuel dossier ouvert
            self._rebuild_list(keep_position=False)

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

    # ----- barre d'outils : tri et filtre de statut -----
    def _build_toolbar(self):
        self.toolbar = QWidget()
        self.toolbar.setObjectName("toolBar")
        hl = QHBoxLayout(self.toolbar)
        hl.setContentsMargins(20, 6, 20, 6)
        hl.setSpacing(6)
        lbl = QLabel(tr("Trier par"))
        lbl.setObjectName("tbLabel")
        hl.addWidget(lbl)
        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("sortCombo")
        self.sort_combo.setAccessibleName(tr("Trier par"))
        for key, label in SORTS:
            self.sort_combo.addItem(tr(label), key)
        self.sort_combo.setCurrentIndex([k for k, _ in SORTS].index(self._sort))
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        hl.addWidget(self.sort_combo)
        hl.addSpacing(18)
        self.status_group = QButtonGroup(self)
        self.status_group.setExclusive(True)
        for key, label in STATUS_FILTERS:
            b = QPushButton(tr(label))
            b.setObjectName("statusChip")
            b.setCheckable(True)
            b.setChecked(key == self._status_filter)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.TabFocus)
            b.setProperty("status", key)
            b.setAccessibleName(tr("Filtrer : {status}", status=tr(label)))
            self.status_group.addButton(b)
            hl.addWidget(b)
        self.status_group.buttonClicked.connect(
            lambda b: self._set_status_filter(b.property("status")))
        hl.addStretch(1)
        self.count_label = QLabel()
        self.count_label.setObjectName("tbCount")
        hl.addWidget(self.count_label)
        return self.toolbar

    def _style_toolbar(self, c):
        self.toolbar.setStyleSheet(f"""
            #toolBar {{ background: {c['list_bg']}; border-bottom: 1px solid {c['border']}; }}
            #tbLabel, #tbCount {{ color: {c['text_dim']}; font-size: 12px; }}
            QComboBox#sortCombo {{ min-width: 130px; }}
            QPushButton#statusChip {{
                color: {c['text_dim']}; background: transparent;
                border: 1px solid {c['border']}; border-radius: 12px;
                padding: 3px 12px; font-size: 12px; font-weight: 600;
                /* 24 px de haut au moins : Qt n'arrondit pas un coin dont le
                   rayon depasse la moitie de la hauteur (cas des polices du Mac) */
                min-height: 16px;
            }}
            QPushButton#statusChip:hover {{ color: {c['text']}; background: {c['button']}; }}
            QPushButton#statusChip:checked {{
                color: {c['text']}; background: {c['button_hover']};
                border-color: {c['text_dim']};
            }}
            QPushButton#statusChip:focus {{ border: 2px solid {theme.ACCENT}; }}
        """)
        self.update_icon.setPixmap(icons.download(c["text"]).pixmap(16, 16))
        self.update_banner.setStyleSheet(f"""
            #updateBanner {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; }}
            #updateText {{ color: {c['text']}; font-size: 13px; }}
            QPushButton#updateLink {{
                color: {theme.ACCENT}; background: transparent; border: none; padding: 0;
                font-size: 13px; text-decoration: underline;
            }}
            QPushButton#updateLater {{
                color: {c['text_dim']}; background: transparent; border: 1px solid {c['border']};
                border-radius: 6px; padding: 4px 12px;
            }}
            QPushButton#updateLater:hover {{ background: {c['button_hover']}; }}
        """)
        self.consent.setStyleSheet(f"""
            #consent {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; }}
            #consentText {{ color: {c['text']}; font-size: 13px; }}
            QPushButton {{
                color: {c['text']}; background: {c['button']};
                border: 1px solid {c['border']}; border-radius: 8px; padding: 5px 14px;
            }}
            QPushButton:hover {{ background: {c['button_hover']}; }}
            QPushButton#consentYes {{
                color: {theme.ON_ACCENT}; background: {theme.ACCENT}; border: none; font-weight: 700;
            }}
            QPushButton#consentYes:hover {{ background: {theme.ACCENT_HOVER}; }}
        """)

    def _on_sort_changed(self, _index):
        self._sort = self.sort_combo.currentData()
        self.store.set_library_pref("sort", self._sort)
        self._rebuild_list(keep_position=False)
        self.list_host.set_position(0)

    def _set_status_filter(self, status):
        self._status_filter = status
        self.store.set_library_pref("status_filter", status)
        for b in self.status_group.buttons():
            b.setChecked(b.property("status") == status)
        self._rebuild_list(keep_position=False)
        self.list_host.set_position(0)

    def _status_label(self):
        return tr(dict(STATUS_FILTERS).get(self._status_filter, ""))

    def _update_count(self):
        """Nombre de tomes et de chapitres affiches, comptes par
        _apply_filter : un dossier de serie compte ses elements - pendant une
        recherche, ceux qui y correspondent."""
        n = self._visible_count
        chapters = self._visible_chapters
        text = units.count_text(n - chapters, chapters) if self._entries else ""
        approx = bool(text) and n > 0 and self._search_approx
        if approx:
            text += " · " + tr("résultats approchants")
        elif text and self.is_remote_source():
            text += " · " + tr("lus en continu depuis le serveur, sans copie sur le disque")
        self.count_label.setText(text)
        self.count_label.setToolTip(
            tr("Aucun résultat exact : les fautes de frappe sont tolérées.") if approx else "")

    # ----- nouvelle version disponible -----
    def _build_update_banner(self):
        self.update_banner = QFrame()
        self.update_banner.setObjectName("updateBanner")
        hl = QHBoxLayout(self.update_banner)
        hl.setContentsMargins(20, 7, 20, 7)
        hl.setSpacing(12)
        self.update_icon = QLabel()
        hl.addWidget(self.update_icon)
        self.update_text = QLabel()
        self.update_text.setObjectName("updateText")
        self.update_text.setTextFormat(Qt.PlainText)
        hl.addWidget(self.update_text)
        link = QPushButton(tr("Voir les nouveautés et télécharger"))
        link.setObjectName("updateLink")
        link.setCursor(Qt.PointingHandCursor)
        link.clicked.connect(self._open_update_page)
        hl.addWidget(link)
        hl.addStretch(1)
        later = QPushButton(tr("Plus tard"))
        later.setObjectName("updateLater")
        later.setCursor(Qt.PointingHandCursor)
        later.clicked.connect(self._dismiss_update)
        hl.addWidget(later)
        self._update = None
        self.update_banner.hide()
        return self.update_banner

    def show_update(self, release):
        """Bandeau « Beheread x.y.z est disponible » (release : voir
        infra/updates.latest_release)."""
        self._update = release
        self.update_text.setText(tr("Beheread {version} est disponible (vous avez la {current}).",
                                    version=release["version"], current=__version__))
        self.update_banner.show()

    def _open_update_page(self):
        if self._update:
            QDesktopServices.openUrl(QUrl(self._update["url"]))

    def _dismiss_update(self):
        """« Plus tard » : cette version n'est plus annoncee (une suivante le sera)."""
        if self._update:
            self.store.set_ui_pref("update_dismissed", self._update["version"])
        self.update_banner.hide()

    # ----- consentement aux metadonnees en ligne -----
    def _build_consent_banner(self):
        self.consent = QFrame()
        self.consent.setObjectName("consent")
        hl = QHBoxLayout(self.consent)
        hl.setContentsMargins(20, 8, 20, 8)
        hl.setSpacing(10)
        text = QLabel(tr("Beheread peut compléter l'auteur et l'année de vos mangas en "
                      "interrogeant Google Books, AniList, MangaDex et la BnF à partir du nom "
                      "des fichiers. Rien d'autre n'est envoyé."))
        text.setObjectName("consentText")
        text.setWordWrap(True)
        hl.addWidget(text, 1)
        yes = QPushButton(tr("Activer"))
        yes.setObjectName("consentYes")
        yes.setCursor(Qt.PointingHandCursor)
        yes.clicked.connect(lambda: self._set_online_metadata(True))
        no = QPushButton(tr("Non merci"))
        no.setCursor(Qt.PointingHandCursor)
        no.clicked.connect(lambda: self._set_online_metadata(False))
        hl.addWidget(yes)
        hl.addWidget(no)
        self.consent.hide()
        return self.consent

    def _online_meta(self) -> bool:
        return self.store.ui_pref("online_metadata") is True

    def _update_consent_banner(self):
        self.consent.setVisible(
            self.store.ui_pref("online_metadata") is None and bool(self._entries))

    def _set_online_metadata(self, enabled: bool):
        was = self._online_meta()
        self.store.set_ui_pref("online_metadata", bool(enabled))
        self.consent.hide()
        if enabled and not was:
            # les echecs de la session venaient du mode hors ligne : on relance
            self.meta.forget_failures()
            self._rebuild_list()

    def _build_empty_panel(self):
        self.empty_panel = QWidget()
        self.empty_panel.setObjectName("emptyPanel")
        v = QVBoxLayout(self.empty_panel)
        v.setSpacing(10)
        v.addStretch(1)
        self.empty_icon = QLabel()
        self.empty_icon.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty_icon)
        self.empty_title = QLabel()
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty_title)
        self.empty_label = QLabel()
        self.empty_label.setObjectName("emptyText")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        v.addWidget(self.empty_label)
        self.empty_btn = QPushButton()
        self.empty_btn.setObjectName("emptyBtn")
        self.empty_btn.setCursor(Qt.PointingHandCursor)
        self.empty_btn.clicked.connect(lambda: self._empty_action and self._empty_action())
        self._empty_action = None
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.empty_btn)
        row.addStretch(1)
        v.addSpacing(6)
        v.addLayout(row)
        v.addStretch(2)
        self.empty_panel.hide()
        return self.empty_panel

    def _set_empty_state(self, title, text, button=None, action=None):
        self.empty_title.setText(title)
        self.empty_label.setText(text)
        self.empty_label.setVisible(bool(text))
        self._empty_action = action
        self.empty_btn.setVisible(bool(button))
        if button:
            self.empty_btn.setText(button)

    def _style_empty_panel(self, c):
        self.empty_icon.setPixmap(icons.folder_plus(c["text_dim"]).pixmap(QSize(64, 64)))
        self.empty_panel.setStyleSheet(f"""
            #emptyPanel {{ background: {c['list_bg']}; }}
            #emptyTitle {{ color: {c['text']}; font-size: 20px; font-weight: 700; }}
            #emptyText {{ color: {c['text_dim']}; font-size: 14px; }}
            QPushButton#emptyBtn {{
                color: {theme.ON_ACCENT}; background: {theme.ACCENT}; border: none;
                border-radius: 8px; padding: 9px 20px;
                font-size: 14px; font-weight: 700;
            }}
            QPushButton#emptyBtn:hover {{ background: {theme.ACCENT_HOVER}; }}
            QPushButton#emptyBtn:focus {{ border: 2px solid {c['text']}; }}
        """)

    def _add_folder_dialog(self):
        """Ajout direct d'un dossier source (etat vide du premier lancement),
        sans passer par le panneau de gestion."""
        folder = QFileDialog.getExistingDirectory(self, tr("Choisir un dossier de mangas"))
        if folder and self.store.add_folder(folder):
            self.refresh()

    # ----- aide des raccourcis -----
    def _toggle_help(self):
        self._help.toggle()

    # ----- glisser-deposer -----
    @staticmethod
    def _dropped_paths(event):
        """(dossiers, fichiers de manga) locaux contenus dans un glisser."""
        folders, files = [], []
        md = event.mimeData()
        if not md.hasUrls():
            return folders, files
        for url in md.urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.is_dir():
                folders.append(str(p))
            elif p.suffix.lower() in SUPPORTED_EXTS and p.is_file():
                files.append(str(p))
        return folders, files

    def dragEnterEvent(self, event):
        folders, files = self._dropped_paths(event)
        if folders or files:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        folders, files = self._dropped_paths(event)
        event.acceptProposedAction()
        added = [f for f in folders if self.store.add_folder(f)]
        if added:
            self.refresh()
        if files:
            self.mangaActivated.emit(files[0])
