"""Lecteur de pages.

Navigation :
  fleche bas / espace / molette bas   -> page suivante
  fleche haut / retour / molette haut -> page precedente
  fleche droite / clic zone droite -> page suivante (page precedente en mode manga)
  fleche gauche / clic zone gauche -> page precedente (page suivante en mode manga)
  PgDown / PgUp : avancer / reculer d'une seule page (utile en mode double)
  Debut / Fin : premiere / derniere page
  D : basculer simple page <-> double page
  M : basculer mode manga (droite -> gauche) <-> mode normal (gauche -> droite)
  S : decaler la parite en double page (couverture seule <-> couplee)
  F : ajustement fenetre -> largeur -> hauteur
  R : recadrage automatique des marges (rogne les bords vides du scan)
  A : activer/desactiver l'Ambilight (fond teinte par la couleur de la page)
  + / - : zoom, 0 : reinitialiser le zoom, Ctrl+molette : zoom
  F11 ou bouton "Plein ecran" (en haut a droite) : plein ecran
  C : masquer instantanement la fenetre (touche "boss") ; Ctrl+Alt+C la
      reaffiche depuis n'importe ou (raccourci global)
  Echap ou bouton "Bibliotheque" (en haut a gauche) : retour a la bibliotheque
  Entree : a la derniere page, passer au tome suivant s'il est detecte
  Barre de defilement en bas de l'ecran : clic ou glisser pour sauter a une page

L'interface (HUD, boutons, barre) s'efface apres quelques secondes d'inactivite
de la souris et reapparait au moindre mouvement (jamais lors d'un simple
changement de page, pour ne pas distraire pendant la lecture au clavier).

Les pages sont decompressees a la volee en memoire, et les pages voisines
sont prechargees dans un thread pour une navigation fluide.

En mode double page, une image plus large que haute (planche double deja
scannee sur une seule image) est automatiquement affichee seule au lieu
d'etre couplee avec sa voisine.

Un fondu enchaine rapide (~130ms) adoucit chaque changement de page.
"""


from PySide6.QtCore import (
    QPoint,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QWidget,
)

from beheread.core import pairing
from beheread.core.wheel_nav import WheelNavigator
from beheread.infra.archive import Archive, find_next_volume
from beheread.infra.storage import Store
from beheread.ui import icons, theme
from beheread.ui.help_overlay import READER_SHORTCUTS, ShortcutOverlay
from beheread.ui.reader.components import NextVolumeProbe, _PageSlider
from beheread.ui.reader.constants import (
    CHROME_HIDE_MS,
    FIT_HEIGHT,
    FIT_WIDTH,
    FIT_WINDOW,
    SLIDER_H,
)
from beheread.ui.reader.display import DisplayMixin
from beheread.ui.reader.end_card import EndCardMixin
from beheread.ui.reader.hud import HudMixin
from beheread.ui.reader.input import InputMixin
from beheread.ui.reader.page_cache import PageCache
from beheread.ui.reader.session import SessionMixin


class ReaderWidget(HudMixin, EndCardMixin, DisplayMixin, InputMixin,
                   SessionMixin, QWidget):
    closed = Signal()
    next_volume_requested = Signal(str)
    volume_finished = Signal(str)   # ce tome vient de passer « termine »
    session_ended = Signal(str)     # fin de la seance de lecture de ce tome (suivi AniList)
    fullscreen_toggled = Signal()

    def __init__(self, path: str, store: Store, parent=None, direct_mode=False):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        # lecture directe (fichier ouvert par double-clic) : le bouton retour
        # quitte l'app au lieu de revenir a la bibliotheque, d'ou un libelle
        # "Quitter" plutot que "Bibliotheque".
        self.direct_mode = direct_mode
        self.store = store
        self.path = path
        self._released = False   # voir release()
        self.archive = Archive(path)          # peut lever ArchiveError
        self.total = len(self.archive)
        store.set_page_count(path, self.total)   # sert aux estimations de la bibliotheque

        self.page = 0
        prog = store.get_progress(path)
        if prog and 0 <= prog[0] < self.total:
            self.page = prog[0]

        self.double_page = bool(store.reader_pref("double_page", True))
        self._series_key = self._resolve_series_key()
        self.manga_mode = self._initial_manga_mode()
        self.fit_mode = int(store.reader_pref("fit_mode", FIT_WINDOW))
        self.smart_crop = bool(store.reader_pref("smart_crop", False))
        self.ambilight = bool(store.reader_pref("ambilight", False))
        self.page_offset = int(store.get_reader_offset(path)) & 1
        self.zoom = 1.0
        self.pan = QPoint(0, 0)
        # alignement a appliquer au prochain rendu d'une page plus haute que
        # l'ecran : "top" en avancant, "bottom" en remontant (molette, fleche haut)
        self._pending_align = "top"
        self._view_geom = None   # (y, hauteur contenu, hauteur vue) du dernier rendu
        self._wheel = WheelNavigator()
        self._drag_origin = None
        self._dragged = False

        # pages decodees : prechargement et eviction dans PageCache (voir
        # page_cache.py) ; self.cache en est la vue en lecture
        self.pages = PageCache(self.archive, self.total, self)
        self.pages.loaded.connect(self._on_page_loaded)
        self.pages.evicted.connect(self._on_page_evicted)
        self.cache = self.pages.images
        self.pool = QThreadPool.globalInstance()

        self._scaled_cache = {}  # (index, w, h, crop) -> QPixmap deja mis a l'echelle
        self._scaled_order = []
        self._crop_cache = {}    # index -> QRect de contenu (recadrage marges) ou None

        # Ambilight : fond teinte par la couleur moyenne (assombrie) de la
        # page courante, avec un fondu doux d'une teinte a l'autre.
        self._theme_bg = None          # fond neutre du theme (repli, Ambilight desactive)
        self._bg_color = None          # fond effectivement peint (anime)
        self._ambient_cache = {}       # index -> QColor moyenne assombrie
        self._bg_from = None
        self._bg_to = None
        self._bg_progress = 1.0
        self._bg_timer = QTimer(self)
        self._bg_timer.timeout.connect(self._step_bg)

        self._next_volume_checked = False
        self._next_volume_path = None
        self._next_volume_probe = None

        # fondu enchaine : on memorise les pixmaps de pages effectivement
        # dessines a la derniere frame (avec leur position) plutot que de
        # capturer tout le widget (self.grab()) - cela evite une allocation
        # plein ecran par tour de page et exclut proprement le HUD du fondu.
        self._last_frame = []         # [(QPixmap, x, y)] de la frame courante
        self._prev_frame = None       # instantane (liste) de la page precedente
        self._transition_progress = 0.0
        self._transition_timer = QTimer(self)
        self._transition_timer.timeout.connect(self._step_transition)

        # estimation du temps restant : horodatage des tours de page (session)
        self._page_times = []
        # statistiques de la seance : pages lues (quittees en avancant) et
        # passage a « termine » pendant la seance
        self._session_pages = set()
        prog = store.get_progress(path)
        self._was_finished = bool(prog and prog[2])

        self._build_hud()

        self.back_button = QPushButton(
            " Quitter" if self.direct_mode else " Bibliothèque", self)
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.setIconSize(QSize(16, 16))
        self.back_button.setFocusPolicy(Qt.NoFocus)
        self.back_button.setAccessibleName(
            "Quitter" if self.direct_mode else "Retour à la bibliothèque")
        self.back_button.adjustSize()
        self.back_button.move(14, 14)
        self.back_button.clicked.connect(self.close_reader)

        self.fullscreen_button = QPushButton(" Plein écran", self)
        self.fullscreen_button.setCursor(Qt.PointingHandCursor)
        self.fullscreen_button.setIconSize(QSize(16, 16))
        self.fullscreen_button.setFocusPolicy(Qt.NoFocus)
        self.fullscreen_button.setAccessibleName("Plein écran")
        self.fullscreen_button.adjustSize()
        self.fullscreen_button.clicked.connect(self.fullscreen_toggled.emit)

        self.page_slider = _PageSlider(Qt.Horizontal, self)
        self.page_slider.setFocusPolicy(Qt.NoFocus)
        self.page_slider.setAccessibleName("Position dans le tome")
        self.page_slider.setCursor(Qt.PointingHandCursor)
        self.page_slider.setMinimum(0)
        self.page_slider.setMaximum(max(0, self.total - 1))
        self.page_slider.setVisible(self.total > 1)
        self.page_slider.scrubbed.connect(self._on_slider_scrub)
        self.page_slider.hovered.connect(self._on_slider_hover)
        self.page_slider.hoverLeft.connect(self._hide_preview)

        # apercu de page au survol de la barre de defilement
        self._preview = QLabel(self)
        self._preview.setObjectName("pagePreview")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._preview.hide()
        self._preview_cache = {}     # index -> QPixmap (apercu reduit)
        self._preview_loaders = {}   # index -> loader en vol
        self._preview_target = None

        self._build_end_card()
        # aide des raccourcis (F1 ou ?), par-dessus la page
        self._help = ShortcutOverlay(READER_SHORTCUTS, self)

        # interface auto-masquable
        self._chrome_visible = True
        self._chrome_timer = QTimer(self)
        self._chrome_timer.setSingleShot(True)
        self._chrome_timer.timeout.connect(self._hide_chrome)

        self.apply_theme()
        self._place_slider()

        self._go_to(self.page, save=False)
        self._chrome_timer.start(CHROME_HIDE_MS)

    # ------------------------------------------------------------ theme
    def apply_theme(self):
        c = theme.colors(self.store.ui_pref("theme", "dark"))
        self._theme_bg = QColor(c["reader_bg"])
        if self._bg_color is None:
            self._bg_color = QColor(self._theme_bg)
        self.hud_info.setStyleSheet(
            f"#hudInfo {{ background: {c['hud_bg']}; border: 1px solid {c['border']};"
            " border-radius: 12px; }"
            f"#hudPos {{ color: {c['text']}; font-size: 15px; font-weight: 700; }}"
            f"#hudSub {{ color: {c['text_dim']}; font-size: 12px; }}")
        self.hud_bar.setStyleSheet(
            f"#hudBar {{ background: {c['hud_bg']}; border: 1px solid {c['border']};"
            " border-radius: 15px; }"
            # bascule ETEINTE : plate, sans contour, texte estompe
            f"QPushButton {{ color: {c['text_dim']}; background: transparent;"
            f" border: 1px solid transparent; border-radius: 11px;"
            " padding: 4px 11px; font-size: 12px; font-weight: 600; }"
            f"QPushButton:hover {{ color: {c['text']};"
            f" background: {c['button']}; }}"
            # bascule ACTIVE : pastille grise pleine "enfoncee", texte plein
            f"QPushButton:checked {{ color: {c['text']}; background: {c['button_hover']};"
            f" border: 1px solid {c['text_dim']}; }}"
            f"QPushButton:checked:hover {{ background: {c['button']}; }}"
            # indisponible (ex. Decalage hors double page) : tres estompe mais
            # toujours en place, pour que la barre ne se decale jamais
            f"QPushButton:disabled {{ color: {c['text_disabled']};"
            " background: transparent; border-color: transparent; }"
            # selecteur / action (non-bascule) : contour neutre permanent,
            # meme survol que les bascules (aucune couleur d'accent ici)
            f"QPushButton#hudSel {{ color: {c['text']};"
            f" border: 1px solid {c['border']}; }}"
            f"QPushButton#hudSel:hover {{ background: {c['button']};"
            f" border-color: {c['text_dim']}; }}"
            # (le selecteur par id est plus specifique : redire :disabled ici)
            f"QPushButton#hudSel:disabled {{ color: {c['text_disabled']};"
            " background: transparent; border-color: transparent; }")
        # meme langage visuel que la barre de reglages (#hudSel) : contour
        # neutre permanent, survol qui remplit en gris - jamais d'accent, pour
        # que "Bibliotheque" et "Plein ecran" s'accordent avec le reste du HUD
        button_css = (
            f"QPushButton {{ color: {c['text']}; background: transparent;"
            f" border: 1px solid {c['border']}; padding: 7px 16px 7px 12px;"
            " border-radius: 18px; font-size: 13px; font-weight: 600; }"
            f"QPushButton:hover {{ background: {c['button']};"
            f" border-color: {c['text_dim']}; }}")
        self.back_button.setStyleSheet(button_css)
        self.fullscreen_button.setStyleSheet(button_css)
        self.back_button.setIcon(icons.chevron_left(c["text"]))
        self.fullscreen_button.setIcon(icons.expand(c["text"]))
        self.back_button.adjustSize()
        self.fullscreen_button.adjustSize()
        self._place_corner_buttons()
        self.page_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ background: {c['hud_bg']};"
            f" height: {SLIDER_H}px; border-radius: {SLIDER_H // 2}px; }}"
            f"QSlider::sub-page:horizontal {{ background: {theme.ACCENT_DIM};"
            f" border-radius: {SLIDER_H // 2}px; }}"
            f"QSlider::handle:horizontal {{ background: {theme.ACCENT}; width: 14px;"
            f" margin: -4px 0; border-radius: 7px; }}")
        self._preview.setStyleSheet(
            f"#pagePreview {{ background: {c['panel']}; color: {c['text_dim']};"
            f" border: 1px solid {c['border']}; border-radius: 6px; }}")
        self._style_end_card(c)
        self._help.apply_colors(c)
        self._update_ambient_target(animate=False)
        self.update()


    def _pairs_with_next(self, p):
        """La page p forme-t-elle une paire avec p+1 en mode double ? Depend du
        decalage de parite (touche S) et des planches doubles (jamais couplees).
        Logique pure dans pairing.py (testee sans Qt)."""
        return pairing.pairs_with_next(p, self.total, self.page_offset,
                                       self.double_page, self._is_spread)

    def _current_indices(self):
        return pairing.current_indices(self.page, self.total, self.page_offset,
                                       self.double_page, self._is_spread)

    def _shift_parity(self):
        """Decale la parite de l'appairage double page (touche S). Pour ne pas
        se retrouver en page simple (la page courante isolee), on garde cette
        page visible en la re-appairant avec sa voisine precedente : la vue
        (p, p+1) devient (p-1, p) - c'est justement la bonne planche double
        quand une couverture en tete de tome decale tout l'appairage. Seule
        exception : tout au debut, la couverture s'affiche seule (pas de
        voisine avant elle). Le choix est memorise pour ce tome."""
        self.page_offset ^= 1
        self.store.set_reader_offset(self.path, self.page_offset)
        # apres inversion, une page qui etait debut de paire devient fin de
        # paire : on recule d'une page pour reafficher une paire (au lieu
        # d'isoler la page courante), sauf a la toute premiere page.
        if (self.double_page and self.page > 0
                and (self.page - self.page_offset) % 2 != 0):
            self._go_to(self.page - 1)
        else:
            self._update_hud()
            self.update()

    def next_page(self, step=None, animate=True):
        step = len(self._current_indices()) if step is None else step
        if self.page + step <= self.total - 1:
            self._go_to(self.page + step, animate=animate)
        elif self.page < self.total - 1:
            self._go_to(self.total - 1, animate=animate)
        else:
            self._save_progress(finished=True)
            if not self._next_volume_checked:
                self._next_volume_checked = True
                self._next_volume_path = find_next_volume(self.path)
            self._show_end_card()

    def prev_page(self, step=None, animate=True, align="top"):
        step = self._step_back() if step is None else step
        self._go_to(max(0, self.page - step), animate=animate, align=align)

    def _step_back(self):
        """Nombre de pages a reculer pour atteindre la page/paire logique
        precedente (logique pure dans pairing.py, testee sans Qt)."""
        return pairing.step_back(self.page, self.total, self.page_offset,
                                 self.double_page, self._is_spread)

    def _go_to(self, index: int, save=True, animate=True, align="top"):
        new_page = max(0, min(index, self.total - 1))
        if new_page > self.page:
            # en avancant, la ou les pages quittees ont ete lues
            self._session_pages.update(self._current_indices())
        if new_page != self.page:
            if animate and self.store.reader_pref("page_fade", True):
                self._start_transition()
            else:
                # navigation rapide (fleche maintenue) : pas de fondu, et on
                # annule celui deja en cours pour ne pas empiler les frames
                # figees ni faire tourner le timer a chaque page.
                self._cancel_transition()
            self._record_page_time()
        self.page = new_page
        self.pan = QPoint(0, 0)
        self._pending_align = align
        self._view_geom = None   # recalcule au prochain rendu (page peut-etre pas encore chargee)
        if self.page < self.total - 1:
            self._hide_end_card()
        self._ensure_loaded()
        self._maybe_prefetch_next_volume()
        if save:
            self._save_progress()
        self.page_slider.setValue(self.page)
        if self.ambilight:
            self._update_ambient_target()
        self._update_hud()
        self.update()

    def _maybe_prefetch_next_volume(self):
        """Des que la lecture depasse ~85% du tome, on cherche et prechauffe le
        tome suivant en arriere-plan (une seule fois), pour que la fiche de fin
        et la touche Entree soient instantanees."""
        if self._next_volume_checked or self.total <= 1:
            return
        if self.page < 0.85 * (self.total - 1):
            return
        self._next_volume_checked = True
        probe = NextVolumeProbe(self.path)
        probe.signals.found.connect(self._on_next_volume_found)
        self._next_volume_probe = probe   # garde une reference (sinon GC)
        self.pool.start(probe)

    def _on_next_volume_found(self, path):
        self._next_volume_path = path
        self._next_volume_probe = None
        # si la fiche de fin est deja affichee (fin atteinte avant la fin du
        # scan), on la met a jour pour reveler le bouton « Tome suivant »
        if self.end_card.isVisible():
            self._show_end_card()

    def _on_slider_scrub(self, value):
        self._go_to(value)


    # ------------------------------------------------------------ cache
    def _ensure_loaded(self):
        self.pages.ensure_around(self.page)

    def _on_page_evicted(self, index: int):
        self._crop_cache.pop(index, None)
        self._ambient_cache.pop(index, None)

    def _on_page_loaded(self, index: int):
        if index in self._current_indices():
            if self.ambilight:
                self._update_ambient_target()
            self.update()


    # ------------------------------------------------------------ rendu
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._bg_color)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        self._draw_pages(painter)

        # fondu enchaine : les pages de la frame precedente se dissipent
        # au-dessus du contenu actuel (le HUD, dessine par des widgets enfants,
        # n'est jamais inclus dans ce fondu).
        if self._prev_frame and self._transition_progress > 0:
            painter.setOpacity(self._transition_progress)
            for pm, px, py in self._prev_frame:
                painter.drawPixmap(px, py, pm)
            painter.setOpacity(1.0)

    def _draw_pages(self, painter):
        indices = self._current_indices()
        for i in indices:
            img = self.cache.get(i)
            if img is None:
                painter.setPen(QColor(theme.colors(self.store.ui_pref("theme", "dark"))["text_dim"]))
                painter.drawText(self.rect(), Qt.AlignCenter, "Chargement…")
                return
            if img.isNull():
                painter.setPen(QColor("#d06060"))
                painter.drawText(self.rect(), Qt.AlignCenter,
                                 f"Page {i + 1} illisible")
                return

        # recadrage partage entre les deux pages (memes marges) le cas echeant
        crops = self._display_crops(indices)
        items = []   # (index, crop_rect|None, largeur_source, hauteur_source)
        for i in indices:
            crop = crops.get(i)
            sz = crop.size() if crop is not None else self.cache[i].size()
            items.append((i, crop, sz.width(), sz.height()))

        if self.manga_mode and len(items) == 2:
            items.reverse()  # RTL : page la plus recente a gauche

        vw, vh = self.width(), self.height()
        ratios = [w / h for (_i, _c, w, h) in items]
        rsum = sum(ratios)

        if self.fit_mode == FIT_WIDTH:
            h = vw / rsum
        elif self.fit_mode == FIT_HEIGHT:
            h = vh
        else:
            h = min(vh, vw / rsum)
        h *= self.zoom
        widths = [h * r for r in ratios]
        total_w = sum(widths)

        x = (vw - total_w) / 2 + self.pan.x()
        y = (vh - h) / 2 + self.pan.y()
        if self._pending_align is not None:
            # page plus haute que l'ecran : on commence en haut (en avancant)
            # ou en bas (en remontant), jamais au milieu
            if h > vh:
                y = 0.0 if self._pending_align == "top" else vh - h
            self._pending_align = None
        if total_w <= vw:
            x = (vw - total_w) / 2
        else:
            x = min(0.0, max(vw - total_w, x))
        if h <= vh:
            y = (vh - h) / 2
        else:
            y = min(0.0, max(vh - h, y))
        self.pan = QPoint(int(x - (vw - total_w) / 2), int(y - (vh - h) / 2))
        self._view_geom = (y, h, vh)

        dpr = self.devicePixelRatioF()
        frame = []
        for (i, crop, _sw, _sh), w in zip(items, widths):
            # on met a l'echelle en pixels physiques (dpr) puis on indique ce
            # ratio au pixmap, sinon Qt re-etire une image deja sous-echantillonnee
            # sur les ecrans HiDPI (perte de nettete visible surtout sans zoom).
            pm = self._scaled_pixmap(i, crop, round(w * dpr), round(h * dpr), dpr)
            painter.drawPixmap(round(x), round(y), pm)
            frame.append((pm, round(x), round(y)))
            x += w
        # memorise la frame courante pour le fondu au prochain changement de page
        self._last_frame = frame

    def resizeEvent(self, event):
        # une page plus haute que l'ecran, calee en haut (ou en bas), le reste
        # apres redimensionnement - notamment quand la fenetre s'agrandit juste
        # apres l'ouverture (sinon la page apparaissait decalee vers le milieu)
        if self._view_geom is not None and self._pending_align is None:
            y, h, vh = self._view_geom
            if h > vh and y >= -0.5:
                self._pending_align = "top"
            elif h > vh and y <= vh - h + 0.5:
                self._pending_align = "bottom"
        # un instantane fige a une autre taille de fenetre ferait un fondu
        # incoherent ; plus simple d'annuler une transition en cours
        self._cancel_transition()
        self._last_frame = []        # pixmaps calibres pour l'ancienne taille
        self._clear_scaled_cache()   # les tailles cibles changent toutes
        self._place_slider()
        self._place_hud()
        self._place_corner_buttons()
        self._place_end_card()
        if self._help.isVisible():
            self._help.show_centered()
        super().resizeEvent(event)


