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

import logging
import time
from pathlib import Path

from PySide6.QtCore import (QObject, QPoint, QRect, QRunnable, QSize, Qt,
                            QThreadPool, QTimer, Signal)
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

import icons
import pairing
import theme
from archive_handler import Archive
from series import find_next_volume, normalize_name, parse_series
from storage import Store

FIT_WINDOW, FIT_WIDTH, FIT_HEIGHT = 0, 1, 2
FIT_NAMES = {FIT_WINDOW: "Ajuster a la fenetre",
             FIT_WIDTH: "Ajuster a la largeur",
             FIT_HEIGHT: "Ajuster a la hauteur"}

PRELOAD_RADIUS = 3   # pages prechargees de chaque cote
CACHE_LIMIT = 12     # pages decodees conservees en memoire
SCALED_CACHE_LIMIT = 8   # pixmaps mis a l'echelle conserves (evite le rescale/frame)

SLIDER_H = 8
SLIDER_SIDE_MARGIN = 20
SLIDER_BOTTOM_MARGIN = 14
HUD_GAP = 8

TRANSITION_MS = 130     # duree totale du fondu entre deux pages
TRANSITION_STEP_MS = 15  # ~60 fps

CHROME_HIDE_MS = 2600   # inactivite souris avant d'effacer l'interface
PAGE_PAUSE_CAP = 90     # secondes : au-dela, on considere une pause (temps ignore)
TIME_MIN_SAMPLES = 4    # tours de page avant d'estimer le temps restant

AMBIENT_DARKEN = 0.35    # facteur d'assombrissement de la couleur moyenne de la page
AMBIENT_MS = 260         # duree du fondu du fond vers la nouvelle teinte
AMBIENT_STEP_MS = 15     # ~60 fps


class _PageSlider(QSlider):
    """Slider dont un clic ou un glisser n'importe ou dans la barre saute
    directement a la position visee (pas de pas incremental). Emet aussi la
    page survolee (sans clic) pour afficher un apercu."""
    scrubbed = Signal(int)
    hovered = Signal(int, int)   # page visee, x (dans le slider) du curseur
    hoverLeft = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)   # recevoir les mouvements sans bouton

    def _value_at(self, x):
        ratio = min(1.0, max(0.0, x / max(1, self.width())))
        return round(self.minimum() + ratio * (self.maximum() - self.minimum()))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            value = self._value_at(event.position().x())
            self.setValue(value)
            self.scrubbed.emit(value)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        x = int(event.position().x())
        if event.buttons() & Qt.LeftButton:
            value = self._value_at(x)
            self.setValue(value)
            self.scrubbed.emit(value)
            event.accept()
            return
        self.hovered.emit(self._value_at(x), x)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hoverLeft.emit()
        super().leaveEvent(event)


class _PageSignals(QObject):
    loaded = Signal(int, QImage)


class PageLoader(QRunnable):
    def __init__(self, archive: Archive, index: int):
        super().__init__()
        self.archive = archive
        self.index = index
        self.signals = _PageSignals()

    def run(self):
        try:
            data = self.archive.read_page(self.index)
            img = QImage.fromData(data)
        except Exception:
            logging.warning("Page %d illisible dans %s",
                            self.index, self.archive.path, exc_info=True)
            img = QImage()
        self.signals.loaded.emit(self.index, img)


class _NextVolumeSignals(QObject):
    found = Signal(object)   # chemin du tome suivant, ou None


class NextVolumeProbe(QRunnable):
    """Cherche le tome suivant (scan du dossier, potentiellement lent sur
    disque reseau) et « chauffe » son archive - ouverture + lecture de la
    premiere page - en arriere-plan, des que la lecture approche de la fin.
    L'enchainement (touche Entree / fiche de fin) devient ainsi instantane :
    ni scan ni premier acces disque a payer au moment ou l'utilisateur agit."""

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.signals = _NextVolumeSignals()

    def run(self):
        try:
            nxt = find_next_volume(self.path)
        except Exception:
            logging.warning("Recherche du tome suivant a %s en echec",
                            self.path, exc_info=True)
            nxt = None
        if nxt:
            try:   # amorce le cache disque de l'OS (open + read + close)
                ar = Archive(nxt)
                ar.read_first_page()
                ar.close()
            except Exception:
                logging.warning("Prechauffage impossible du tome suivant %s", nxt, exc_info=True)
        self.signals.found.emit(nxt)


class ReaderWidget(QWidget):
    closed = Signal()
    next_volume_requested = Signal(str)
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
        self._drag_origin = None
        self._dragged = False

        self.cache = {}          # index -> QImage
        self.cache_order = []
        self.pending = set()
        self.pool = QThreadPool.globalInstance()
        self._loaders = {}       # index -> loader en vol (evite un GC premature)

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

        self._build_hud()

        self.back_button = QPushButton(
            " Quitter" if self.direct_mode else " Bibliotheque", self)
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.setIconSize(QSize(16, 16))
        self.back_button.setFocusPolicy(Qt.NoFocus)
        self.back_button.adjustSize()
        self.back_button.move(14, 14)
        self.back_button.clicked.connect(self.close_reader)

        self.fullscreen_button = QPushButton(" Plein ecran", self)
        self.fullscreen_button.setCursor(Qt.PointingHandCursor)
        self.fullscreen_button.setIconSize(QSize(16, 16))
        self.fullscreen_button.setFocusPolicy(Qt.NoFocus)
        self.fullscreen_button.adjustSize()
        self.fullscreen_button.clicked.connect(self.fullscreen_toggled.emit)

        self.page_slider = _PageSlider(Qt.Horizontal, self)
        self.page_slider.setFocusPolicy(Qt.NoFocus)
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
            f"QPushButton:disabled {{ color: {c['border']};"
            " background: transparent; border-color: transparent; }"
            # selecteur / action (non-bascule) : contour neutre permanent,
            # meme survol que les bascules (aucune couleur d'accent ici)
            f"QPushButton#hudSel {{ color: {c['text']};"
            f" border: 1px solid {c['border']}; }}"
            f"QPushButton#hudSel:hover {{ background: {c['button']};"
            f" border-color: {c['text_dim']}; }}"
            # (le selecteur par id est plus specifique : redire :disabled ici)
            f"QPushButton#hudSel:disabled {{ color: {c['border']};"
            " background: transparent; border-color: transparent; }")
        # meme langage visuel que la barre de reglages (#hudSel) : contour
        # neutre permanent, survol qui remplit en gris - jamais de rouge, pour
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
        self._update_ambient_target(animate=False)
        self.update()

    def _place_corner_buttons(self):
        self.back_button.move(14, 14)
        self.fullscreen_button.move(self.width() - self.fullscreen_button.width() - 14, 14)

    # ------------------------------------------------------------ interface auto-masquable
    def _chrome_widgets(self):
        return (self.hud_info, self.hud_bar, self.back_button,
                self.fullscreen_button, self.page_slider)

    def _show_chrome(self):
        """Reaffiche l'interface (sur mouvement souris) et rearme l'effacement."""
        if not self._chrome_visible:
            self._chrome_visible = True
            for w in (self.hud_info, self.hud_bar, self.back_button,
                      self.fullscreen_button):
                w.setVisible(True)
            self.page_slider.setVisible(self.total > 1)
            self.unsetCursor()
        self._chrome_timer.start(CHROME_HIDE_MS)

    def _hide_chrome(self):
        if self.end_card.isVisible():
            # ne pas masquer l'interface tant que la fiche de fin est affichee
            self._chrome_timer.start(CHROME_HIDE_MS)
            return
        self._chrome_visible = False
        for w in self._chrome_widgets():
            w.setVisible(False)
        self._hide_preview()
        self.setCursor(Qt.BlankCursor)

    # ------------------------------------------------------------ pages
    def _content_rect(self, index):
        """QRect du contenu utile (marges rognees) pour cette page, ou None si
        aucun recadrage pertinent. Calcule une fois puis mis en cache."""
        if index in self._crop_cache:
            return self._crop_cache[index]
        img = self.cache.get(index)
        rect = self._compute_content_rect(img) if img and not img.isNull() else None
        self._crop_cache[index] = rect
        return rect

    @staticmethod
    def _compute_content_rect(img: QImage):
        """Detecte le rectangle de contenu en rognant les bords quasi uniformes
        (marges blanches OU noires). Travaille sur une version reduite en
        niveaux de gris pour rester rapide."""
        w0, h0 = img.width(), img.height()
        if w0 < 40 or h0 < 40:
            return None
        sw = 120
        sh = max(1, round(h0 * sw / w0))
        small = img.scaled(sw, sh, Qt.IgnoreAspectRatio,
                           Qt.FastTransformation).convertToFormat(QImage.Format_Grayscale8)

        def gray(x, y):
            return small.pixel(x, y) & 0xFF

        # couleur de fond = mediane des quatre coins (gere marges claires/sombres)
        corners = sorted([gray(0, 0), gray(sw - 1, 0), gray(0, sh - 1), gray(sw - 1, sh - 1)])
        bg = corners[1]
        thresh = 32
        min_pixels = max(2, sw // 60)   # ignore quelques pixels de bruit isoles

        def row_has_content(y):
            n = sum(1 for x in range(sw) if abs(gray(x, y) - bg) > thresh)
            return n > min_pixels

        def col_has_content(x, y0, y1):
            n = sum(1 for y in range(y0, y1 + 1) if abs(gray(x, y) - bg) > thresh)
            return n > min_pixels

        top = 0
        while top < sh and not row_has_content(top):
            top += 1
        if top >= sh:
            return None   # page uniforme (page blanche/noire) : pas de recadrage
        bottom = sh - 1
        while bottom > top and not row_has_content(bottom):
            bottom -= 1
        left = 0
        while left < sw and not col_has_content(left, top, bottom):
            left += 1
        right = sw - 1
        while right > left and not col_has_content(right, top, bottom):
            right -= 1

        # remise a l'echelle vers l'image pleine resolution + petite marge
        fx, fy = w0 / sw, h0 / sh
        pad_x, pad_y = round(w0 * 0.01), round(h0 * 0.01)
        x = max(0, int(left * fx) - pad_x)
        y = max(0, int(top * fy) - pad_y)
        rx = min(w0, int((right + 1) * fx) + pad_x)
        ry = min(h0, int((bottom + 1) * fy) + pad_y)
        cw, ch = rx - x, ry - y
        if cw <= 0 or ch <= 0:
            return None
        # recadrage negligeable (moins de 3% rogne sur chaque axe) : inutile
        if cw >= w0 * 0.97 and ch >= h0 * 0.97:
            return None
        return QRect(x, y, cw, ch)

    def _content_margins(self, index):
        """Marges de contenu (gauche, haut, droite, bas) en fractions [0,1) des
        dimensions de la page, ou None si aucun recadrage pertinent."""
        img = self.cache.get(index)
        rect = self._content_rect(index)
        if img is None or img.isNull() or rect is None:
            return None
        w, h = img.width(), img.height()
        return (rect.left() / w, rect.top() / h,
                (w - rect.right() - 1) / w, (h - rect.bottom() - 1) / h)

    def _rect_from_margins(self, index, margins):
        img = self.cache[index]
        w, h = img.width(), img.height()
        l, t, r, b = margins
        x = int(round(l * w))
        y = int(round(t * h))
        x1 = int(round((1 - r) * w))
        y1 = int(round((1 - b) * h))
        return QRect(x, y, max(1, x1 - x), max(1, y1 - y))

    def _display_crops(self, indices):
        """Rectangles de recadrage a appliquer pour l'affichage courant.
        En double page, les deux pages partagent le MEME niveau de recadrage :
        on retient, bord par bord, la marge la plus faible des deux (le
        recadrage le moins agressif), pour que les deux planches restent
        alignees et a la meme echelle."""
        if not self.smart_crop:
            return {i: None for i in indices}
        if len(indices) == 1:
            return {indices[0]: self._content_rect(indices[0])}
        margins = [self._content_margins(i) for i in indices]
        if any(m is None for m in margins):
            # au moins une page ne se recadre pas -> aucune des deux (le moins agressif)
            return {i: None for i in indices}
        shared = tuple(min(m[k] for m in margins) for k in range(4))
        return {i: self._rect_from_margins(i, shared) for i in indices}

    def _effective_size(self, index):
        """Taille de la source affichee pour cette page (rognee si recadrage
        actif), ou None si l'image n'est pas encore disponible. Sert a la
        detection des planches doubles (appairage), independamment du partage
        de recadrage entre deux pages voisines."""
        img = self.cache.get(index)
        if img is None or img.isNull():
            return None
        if self.smart_crop:
            r = self._content_rect(index)
            if r is not None:
                return r.size()
        return img.size()

    def _is_spread(self, index):
        """Une image plus large que haute couvre deja une double page (scan
        de planche double) : elle doit s'afficher seule, jamais couplee."""
        s = self._effective_size(index)
        return s is not None and s.width() > s.height()

    # ------------------------------------------------------------ ambilight
    @staticmethod
    def _average_color(img: QImage) -> QColor:
        """Couleur moyenne approximative de l'image : Qt lisse en la reduisant
        a 1x1 pixel, bien plus rapide qu'un parcours manuel des pixels."""
        small = img.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return QColor(small.pixel(0, 0))

    @staticmethod
    def _darken(color: QColor, factor: float = AMBIENT_DARKEN) -> QColor:
        return QColor(int(color.red() * factor), int(color.green() * factor),
                      int(color.blue() * factor))

    def _ambient_color_for(self, index):
        """Couleur de fond Ambilight pour cette page (moyenne assombrie),
        mise en cache. None si la page n'est pas encore decodee."""
        if index in self._ambient_cache:
            return self._ambient_cache[index]
        img = self.cache.get(index)
        if img is None or img.isNull():
            return None
        color = self._darken(self._average_color(img))
        self._ambient_cache[index] = color
        return color

    def _update_ambient_target(self, animate=True):
        """Determine la couleur de fond visee (celle de la page courante en
        Ambilight, sinon le fond neutre du theme) et lance la transition."""
        if self._theme_bg is None:
            return
        if self.ambilight:
            idx = self._current_indices()[0]
            color = self._ambient_color_for(idx)
            target = color if color is not None else self._theme_bg
        else:
            target = self._theme_bg
        self._set_bg_target(target, animate=animate)

    def _set_bg_target(self, color: QColor, animate=True):
        if self._bg_color is not None and color.getRgb() == self._bg_color.getRgb():
            return
        if not animate or self._bg_color is None:
            self._bg_timer.stop()
            self._bg_color = QColor(color)
            self.update()
            return
        self._bg_from = QColor(self._bg_color)
        self._bg_to = QColor(color)
        self._bg_progress = 0.0
        self._bg_timer.start(AMBIENT_STEP_MS)

    def _step_bg(self):
        self._bg_progress = min(1.0, self._bg_progress + AMBIENT_STEP_MS / AMBIENT_MS)
        t = self._bg_progress
        r = self._bg_from.red() + (self._bg_to.red() - self._bg_from.red()) * t
        g = self._bg_from.green() + (self._bg_to.green() - self._bg_from.green()) * t
        b = self._bg_from.blue() + (self._bg_to.blue() - self._bg_from.blue()) * t
        self._bg_color = QColor(int(r), int(g), int(b))
        if self._bg_progress >= 1.0:
            self._bg_timer.stop()
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

    def prev_page(self, step=None, animate=True):
        step = self._step_back() if step is None else step
        self._go_to(max(0, self.page - step), animate=animate)

    def _step_back(self):
        """Nombre de pages a reculer pour atteindre la page/paire logique
        precedente (logique pure dans pairing.py, testee sans Qt)."""
        return pairing.step_back(self.page, self.total, self.page_offset,
                                 self.double_page, self._is_spread)

    def _go_to(self, index: int, save=True, animate=True):
        new_page = max(0, min(index, self.total - 1))
        if new_page != self.page:
            if animate:
                self._start_transition()
            else:
                # navigation rapide (fleche maintenue) : pas de fondu, et on
                # annule celui deja en cours pour ne pas empiler les frames
                # figees ni faire tourner le timer a chaque page.
                self._cancel_transition()
            self._record_page_time()
        self.page = new_page
        self.pan = QPoint(0, 0)
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

    # ------------------------------------------------------------ apercu au survol du slider
    PREVIEW_W, PREVIEW_H = 150, 210

    def _on_slider_hover(self, index, slider_x):
        if not (0 <= index < self.total):
            return
        self._preview_target = index
        pm = self._preview_pixmap(index)
        if pm is None:
            self._preview.setText("…")
            self._preview.setFixedSize(self.PREVIEW_W, self.PREVIEW_H)
        else:
            self._preview.setFixedSize(pm.size())
            self._preview.setPixmap(pm)
        # centre l'apercu sur le curseur, au-dessus du slider, borne a la fenetre
        gx = self.page_slider.x() + slider_x
        w = self._preview.width()
        x = max(8, min(self.width() - w - 8, gx - w // 2))
        y = self.page_slider.y() - self._preview.height() - 10
        self._preview.move(x, max(8, y))
        self._preview.show()
        self._preview.raise_()

    def _hide_preview(self):
        self._preview_target = None
        self._preview.hide()

    def _preview_pixmap(self, index):
        """Vignette d'apercu de la page, depuis le cache d'apercu ou le cache de
        pages deja decodees ; sinon declenche un decodage en arriere-plan."""
        pm = self._preview_cache.get(index)
        if pm is not None:
            return pm
        img = self.cache.get(index)
        if img is not None and not img.isNull():
            return self._make_preview(index, img)
        if index not in self._preview_loaders and index not in self.pending:
            loader = PageLoader(self.archive, index)
            loader.signals.loaded.connect(self._on_preview_loaded)
            self._preview_loaders[index] = loader
            self.pool.start(loader)
        return None

    def _make_preview(self, index, img):
        pm = QPixmap.fromImage(img).scaled(
            self.PREVIEW_W, self.PREVIEW_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._preview_cache[index] = pm
        if len(self._preview_cache) > 40:
            self._preview_cache.pop(next(iter(self._preview_cache)))
        return pm

    def _on_preview_loaded(self, index, image):
        self._preview_loaders.pop(index, None)
        if image.isNull():
            return
        pm = self._make_preview(index, image)
        # n'affiche que si le curseur est toujours sur cette page
        if self._preview_target == index and self._preview.isVisible():
            self._preview.setFixedSize(pm.size())
            self._preview.setPixmap(pm)
            gx = self.page_slider.x() + self.page_slider.width() * index // max(1, self.total - 1)
            w = self._preview.width()
            x = max(8, min(self.width() - w - 8, gx - w // 2))
            self._preview.move(x, max(8, self.page_slider.y() - self._preview.height() - 10))

    # ------------------------------------------------------------ transition
    def _start_transition(self):
        """Fige les pixmaps de la page courante (positionnes) pour les fondre
        au-dessus de la nouvelle page pendant TRANSITION_MS. Pas de self.grab()
        (qui allouerait tout le widget et engloberait le HUD dans le fondu)."""
        if self.width() <= 0 or self.height() <= 0 or not self._last_frame:
            self._prev_frame = None
            return
        self._prev_frame = self._last_frame
        self._transition_progress = 1.0
        self._transition_timer.start(TRANSITION_STEP_MS)

    def _step_transition(self):
        self._transition_progress -= TRANSITION_STEP_MS / TRANSITION_MS
        if self._transition_progress <= 0:
            self._transition_progress = 0.0
            self._transition_timer.stop()
            self._prev_frame = None
        self.update()

    def _cancel_transition(self):
        """Arrete net un fondu en cours (timer + frame figee)."""
        self._transition_timer.stop()
        self._transition_progress = 0.0
        self._prev_frame = None

    def _save_progress(self, finished=None):
        if finished is None:
            last = max(self._current_indices())
            finished = last >= self.total - 1
            prev = self.store.get_progress(self.path)
            if prev and prev[2]:
                finished = True  # ne pas "determiner" un manga deja fini
        self.store.set_progress(self.path, self.page, self.total, finished)

    # ------------------------------------------------------------ temps restant
    def _record_page_time(self):
        self._page_times.append(time.monotonic())
        if len(self._page_times) > 60:
            self._page_times = self._page_times[-60:]

    def _page_deltas(self):
        """Intervalles entre tours de page, hors pauses (cafe, interruption)."""
        deltas = []
        for a, b in zip(self._page_times, self._page_times[1:]):
            d = b - a
            if 0 < d <= PAGE_PAUSE_CAP:
                deltas.append(d)
        return deltas

    def _active_seconds(self):
        return sum(self._page_deltas())

    def _time_remaining_text(self):
        deltas = self._page_deltas()
        if len(deltas) < TIME_MIN_SAMPLES:
            return ""
        deltas = sorted(deltas)
        median = deltas[len(deltas) // 2]
        remaining_pages = max(0, (self.total - 1) - self.page)
        if remaining_pages <= 0:
            return ""
        minutes = median * remaining_pages / 60.0
        if minutes < 1:
            return "moins d'une minute restante"
        return f"~{int(round(minutes))} min restantes"

    @staticmethod
    def _fmt_duration(seconds):
        seconds = int(seconds)
        if seconds < 60:
            return f"{seconds} s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} min"
        return f"{minutes // 60} h {minutes % 60:02d}"

    # ------------------------------------------------------------ cache
    def _ensure_loaded(self):
        wanted = set()
        for d in range(-PRELOAD_RADIUS, PRELOAD_RADIUS + 2):
            i = self.page + d
            if 0 <= i < self.total:
                wanted.add(i)
        for i in sorted(wanted, key=lambda x: abs(x - self.page)):
            if i not in self.cache and i not in self.pending:
                self.pending.add(i)
                loader = PageLoader(self.archive, i)
                loader.signals.loaded.connect(self._on_page_loaded)
                self._loaders[i] = loader
                self.pool.start(loader)

    def _on_page_loaded(self, index: int, image: QImage):
        self.pending.discard(index)
        self._loaders.pop(index, None)   # le runnable termine : on lache la reference
        self.cache[index] = image
        self.cache_order.append(index)
        while len(self.cache_order) > CACHE_LIMIT:
            old = self.cache_order.pop(0)
            if abs(old - self.page) > PRELOAD_RADIUS and old in self.cache:
                del self.cache[old]
                self._crop_cache.pop(old, None)
                self._ambient_cache.pop(old, None)
        if index in self._current_indices():
            if self.ambilight:
                self._update_ambient_target()
            self.update()

    def _scaled_pixmap(self, index, crop, target_w, target_h, dpr):
        """Pixmap de la page (recadree selon `crop` si fourni) mis a l'echelle a
        la taille cible, memorise par (index, recadrage, taille). Evite de
        refaire un rescale couteux a chaque frame (fondu, panoramique)."""
        crop_key = (crop.x(), crop.y(), crop.width(), crop.height()) if crop is not None else None
        key = (index, crop_key, target_w, target_h)
        pm = self._scaled_cache.get(key)
        if pm is not None:
            return pm
        img = self.cache[index]
        src = img.copy(crop) if crop is not None else img
        pm = QPixmap.fromImage(src).scaled(
            QSize(target_w, target_h), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self._scaled_cache[key] = pm
        self._scaled_order.append(key)
        while len(self._scaled_order) > SCALED_CACHE_LIMIT:
            self._scaled_cache.pop(self._scaled_order.pop(0), None)
        return pm

    def _clear_scaled_cache(self):
        self._scaled_cache.clear()
        self._scaled_order.clear()

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
                painter.drawText(self.rect(), Qt.AlignCenter, "Chargement...")
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
        if total_w <= vw:
            x = (vw - total_w) / 2
        else:
            x = min(0.0, max(vw - total_w, x))
        if h <= vh:
            y = (vh - h) / 2
        else:
            y = min(0.0, max(vh - h, y))
        self.pan = QPoint(int(x - (vw - total_w) / 2), int(y - (vh - h) / 2))

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
        # un instantane fige a une autre taille de fenetre ferait un fondu
        # incoherent ; plus simple d'annuler une transition en cours
        self._cancel_transition()
        self._last_frame = []        # pixmaps calibres pour l'ancienne taille
        self._clear_scaled_cache()   # les tailles cibles changent toutes
        self._place_slider()
        self._place_hud()
        self._place_corner_buttons()
        self._place_end_card()
        super().resizeEvent(event)

    # ------------------------------------------------------------ HUD
    def _build_hud(self):
        """Construit le HUD : a gauche un bloc de lecture (position, progression,
        temps restant), a droite une barre de reglages cliquables (chips) qui
        refletent l'etat courant et exposent le raccourci en infobulle."""
        # --- bloc de lecture (info, non interactif : laisse passer les clics)
        self.hud_info = QFrame(self)
        self.hud_info.setObjectName("hudInfo")
        self.hud_info.setAttribute(Qt.WA_TransparentForMouseEvents)
        info_col = QVBoxLayout(self.hud_info)
        info_col.setContentsMargins(14, 8, 14, 8)
        info_col.setSpacing(1)
        self.hud_pos = QLabel(self.hud_info)
        self.hud_pos.setObjectName("hudPos")
        self.hud_sub = QLabel(self.hud_info)
        self.hud_sub.setObjectName("hudSub")
        info_col.addWidget(self.hud_pos)
        info_col.addWidget(self.hud_sub)

        # --- barre de reglages (chips cliquables)
        self.hud_bar = QFrame(self)
        self.hud_bar.setObjectName("hudBar")
        bar = QHBoxLayout(self.hud_bar)
        bar.setContentsMargins(6, 5, 6, 5)
        bar.setSpacing(4)

        def chip(text, handler, tip, checkable=True, name=None):
            b = QPushButton(text, self.hud_bar)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCheckable(checkable)
            b.setToolTip(tip)
            if name:
                b.setObjectName(name)
            b.clicked.connect(lambda: (handler(), self._show_chrome()))
            bar.addWidget(b)
            return b

        # Boutons a bascule oui/non : le libelle nomme la fonction (fixe), l'etat
        # actif se lit a l'apparence (bouton gris "enfonce"), pas au texte.
        self.chip_pagemode = chip(
            "Double page", self.toggle_double_page,
            "Afficher deux pages cote a cote  (D)")
        self.chip_direction = chip(
            "Manga", self.toggle_manga_mode,
            "Lecture droite -> gauche  (M)")
        self.chip_crop = chip(
            "Recadrage auto", self.toggle_smart_crop,
            "Rogner les marges du scan  (R)")
        self.chip_ambilight = chip(
            "Ambilight", self.toggle_ambilight,
            "Fond teinte par la page  (A)")
        # Selecteur multi-etats et action ponctuelle : pas des bascules oui/non,
        # style neutre (contour) et libelle qui montre la valeur / l'action.
        self.chip_fit = chip(
            "", self.cycle_fit_mode, "", checkable=False, name="hudSel")
        self.chip_offset = chip(
            "Decalage", self._shift_parity,
            "Decaler l'appairage des planches  (S)",
            checkable=False, name="hudSel")

    # --- bascules (partagees par le clavier et les chips du HUD) -----------
    def toggle_double_page(self):
        self.double_page = not self.double_page
        self.store.set_reader_pref("double_page", self.double_page)
        self._go_to(self.page)

    def toggle_manga_mode(self):
        self.manga_mode = not self.manga_mode
        self.store.set_reader_pref("manga_mode", self.manga_mode)
        self.store.set_reading_direction(self.path, self._series_key, self.manga_mode)
        self._update_hud()
        self.update()

    def _resolve_series_key(self):
        """Cle de regroupement de serie pour ce tome (meme logique que la
        bibliotheque : override manuel prioritaire, sinon numero de tome
        detecte dans le nom de fichier). None si le tome est seul (pas de
        serie), auquel cas le sens de lecture est memorise par tome."""
        override = self.store.series_override(self.path)
        if override == Store.SERIES_DETACHED:
            return None
        if override:
            return normalize_name(override)
        sname, svolume = parse_series(Path(self.path).stem)
        if svolume is None:
            return None
        return normalize_name(sname)

    def _detect_manga_mode(self):
        """Sens de lecture detecte automatiquement, sans requete reseau (le
        lecteur reste hors ligne) - trois paliers, par ordre de priorite :

        1. "manga" : genre AniList deja mis en cache (par la bibliotheque, au
           survol/scan) pour ce tome ou sa serie, avec pays d'origine connu -
           trouve dans la base manga d'AniList et pays hors Coree/Chine ->
           droite -> gauche (couvre un manga francais comme Radiant, malgre
           son pays d'origine) ; manhwa/manhua (Coree/Chine), presque
           toujours numeriques et lus gauche -> droite, font exception.
        2. "japon" : trouve dans la meme base mais sans pays d'origine
           renseigne - on suppose Japon par defaut (cas tres largement
           majoritaire) -> droite -> gauche.
        3. "xml" : rien en cache AniList pour ce tome/cette serie (jamais
           interroge) -> repli sur ComicInfo.xml (champ Manga), local a
           l'archive.

        Rien de neuf n'est interroge ici pour AniList - seul le cache local
        (meta_cache.json) est lu. None si aucune de ces sources ne donne
        d'indice exploitable."""
        for cached in (self.store.volume_meta(self.path),
                      self.store.series_meta(self._series_key) if self._series_key else None):
            if not cached or cached.get("not_found"):
                continue
            if "country" not in cached:
                continue   # cache ComicInfo/Google Books : pas une entree AniList
            country = (cached.get("country") or "").upper()
            if country:
                return country not in ("KR", "CN")   # palier "manga"
            return True                              # palier "japon" (pays inconnu)

        try:
            info = self.archive.read_comicinfo()
        except Exception:
            info = None
        direction = (info or {}).get("reading_direction")   # palier "xml"
        if direction == "rtl":
            return True
        if direction == "ltr":
            return False
        return None

    def _initial_manga_mode(self):
        """Priorite : choix explicite de l'utilisateur (par serie si ce tome
        en fait partie, sinon par tome) > detection automatique (ComicInfo.xml)
        > reglage global par defaut."""
        saved = self.store.reading_direction(self.path, self._series_key)
        if saved is not None:
            return saved
        detected = self._detect_manga_mode()
        if detected is not None:
            return detected
        return bool(self.store.reader_pref("manga_mode", True))

    def cycle_fit_mode(self):
        self.fit_mode = (self.fit_mode + 1) % 3
        self.store.set_reader_pref("fit_mode", self.fit_mode)
        self.zoom = 1.0
        self._clear_scaled_cache()
        self._go_to(self.page)

    def toggle_smart_crop(self):
        self.smart_crop = not self.smart_crop
        self.store.set_reader_pref("smart_crop", self.smart_crop)
        self._clear_scaled_cache()
        self._update_hud()
        self.update()

    def toggle_ambilight(self):
        self.ambilight = not self.ambilight
        self.store.set_reader_pref("ambilight", self.ambilight)
        self._update_ambient_target()
        self._update_hud()

    def _update_hud(self, extra=""):
        pages = self._current_indices()
        if len(pages) == 2:
            self.hud_pos.setText(f"Pages {pages[0] + 1}-{pages[1] + 1} / {self.total}")
        else:
            self.hud_pos.setText(f"Page {pages[0] + 1} / {self.total}")

        percent = round((pages[-1] + 1) / self.total * 100) if self.total else 0
        sub = [f"{percent}%"]
        remaining = self._time_remaining_text()
        if remaining:
            sub.append(remaining)
        if self.zoom != 1.0:
            sub.append(f"Zoom {int(self.zoom * 100)}%")
        if extra:
            sub.append(extra)
        self.hud_sub.setText("  ·  ".join(sub))

        # bascules oui/non : seul l'etat "coche" (bouton gris) change, jamais le
        # libelle -> on active bien ce sur quoi on clique.
        self.chip_pagemode.setChecked(self.double_page)
        self.chip_direction.setChecked(self.manga_mode)
        self.chip_crop.setChecked(self.smart_crop)
        self.chip_ambilight.setChecked(self.ambilight)

        # selecteur d'ajustement : montre la valeur courante (3 etats)
        fit_short = {FIT_WINDOW: "Fenetre", FIT_WIDTH: "Largeur", FIT_HEIGHT: "Hauteur"}
        self.chip_fit.setText(f"Ajuste: {fit_short[self.fit_mode]}")
        self.chip_fit.setToolTip(FIT_NAMES[self.fit_mode] + " (cliquer pour changer)  (F)")

        # decalage : pertinent seulement en double page. Desactive (grise) au
        # lieu de masque, pour que la barre garde une largeur stable.
        self.chip_offset.setEnabled(self.double_page)

        self.hud_info.adjustSize()
        self.hud_bar.adjustSize()
        self._place_hud()

    def _place_slider(self):
        y = self.height() - SLIDER_BOTTOM_MARGIN - SLIDER_H
        w = max(0, self.width() - SLIDER_SIDE_MARGIN * 2)
        self.page_slider.setGeometry(SLIDER_SIDE_MARGIN, y, w, SLIDER_H)

    def _place_hud(self):
        slider_top = self.height() - SLIDER_BOTTOM_MARGIN - SLIDER_H
        self.hud_info.move(
            SLIDER_SIDE_MARGIN,
            slider_top - self.hud_info.height() - HUD_GAP)
        self.hud_bar.move(
            self.width() - self.hud_bar.width() - SLIDER_SIDE_MARGIN,
            slider_top - self.hud_bar.height() - HUD_GAP)

    # ------------------------------------------------------------ fiche de fin de tome
    def _build_end_card(self):
        self.end_card = QFrame(self)
        self.end_card.setObjectName("endCard")
        v = QVBoxLayout(self.end_card)
        v.setContentsMargins(28, 26, 28, 22)
        v.setSpacing(12)

        self.end_cover = QLabel(self.end_card)
        self.end_cover.setAlignment(Qt.AlignCenter)
        v.addWidget(self.end_cover, alignment=Qt.AlignCenter)

        self.end_title = QLabel(self.end_card)
        self.end_title.setObjectName("endTitle")
        self.end_title.setAlignment(Qt.AlignCenter)
        self.end_title.setWordWrap(True)
        v.addWidget(self.end_title)

        self.end_stats = QLabel(self.end_card)
        self.end_stats.setObjectName("endStats")
        self.end_stats.setAlignment(Qt.AlignCenter)
        v.addWidget(self.end_stats)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.end_next_btn = QPushButton("Tome suivant", self.end_card)
        self.end_next_btn.setCursor(Qt.PointingHandCursor)
        self.end_next_btn.setFocusPolicy(Qt.NoFocus)
        self.end_next_btn.clicked.connect(self._on_end_next)
        self.end_lib_btn = QPushButton(
            "Quitter" if self.direct_mode else "Bibliotheque", self.end_card)
        self.end_lib_btn.setCursor(Qt.PointingHandCursor)
        self.end_lib_btn.setFocusPolicy(Qt.NoFocus)
        self.end_lib_btn.clicked.connect(self.close_reader)
        row.addWidget(self.end_next_btn)
        row.addWidget(self.end_lib_btn)
        v.addLayout(row)

        self.end_card.hide()

    def _style_end_card(self, c):
        self.end_card.setStyleSheet(f"""
            #endCard {{
                background: {c['panel']};
                border: 1px solid {c['border']};
                border-radius: 16px;
            }}
            #endTitle {{ color: {c['text']}; font-size: 18px; font-weight: 700; }}
            #endStats {{ color: {c['text_dim']}; font-size: 13px; }}
            QPushButton {{
                color: {c['text']}; background: transparent;
                border: 1px solid {c['border']}; padding: 9px 18px;
                border-radius: 18px; font-size: 13px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {c['button']}; border-color: {c['text_dim']}; }}
            #endCard QPushButton#endNext {{ background: {theme.ACCENT}; color: #f5f0ee; border: none; }}
            #endCard QPushButton#endNext:hover {{ background: {theme.ACCENT}; border: none; }}
        """)
        self.end_next_btn.setObjectName("endNext")

    def _show_end_card(self):
        name = Path(self.path).stem
        self.end_title.setText(name)

        cover = QPixmap(str(self.store.thumb_path(self.path)))
        if cover.isNull() and 0 in self.cache and not self.cache[0].isNull():
            cover = QPixmap.fromImage(self.cache[0])
        if not cover.isNull():
            self.end_cover.setPixmap(cover.scaled(
                150, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.end_cover.show()
        else:
            self.end_cover.hide()

        active = self._fmt_duration(self._active_seconds())
        parts = [f"{self.total} pages", "Tome termine"]
        if self._active_seconds() > 5:
            parts.insert(1, f"lu en {active}")
        self.end_stats.setText("  ·  ".join(parts))

        if self._next_volume_path:
            self.end_next_btn.setText(f"Tome suivant : {Path(self._next_volume_path).stem}")
            self.end_next_btn.show()
        else:
            self.end_next_btn.hide()

        self.end_card.adjustSize()
        self._place_end_card()
        self._show_chrome()
        self.end_card.show()
        self.end_card.raise_()

    def _place_end_card(self):
        self.end_card.adjustSize()
        cw, ch = self.end_card.width(), self.end_card.height()
        self.end_card.move((self.width() - cw) // 2, (self.height() - ch) // 2)

    def _hide_end_card(self):
        if self.end_card.isVisible():
            self.end_card.hide()

    def _on_end_next(self):
        if self._next_volume_path:
            self.next_volume_requested.emit(self._next_volume_path)

    # ------------------------------------------------------------ entrees
    def keyPressEvent(self, event):
        key = event.key()
        # touche maintenue (auto-repeat) : on saute le fondu pour ne pas
        # empiler les transitions et effondrer les perfs en navigation rapide.
        animate = not event.isAutoRepeat()
        if key in (Qt.Key_Down, Qt.Key_Space):
            self.next_page(animate=animate)
        elif key in (Qt.Key_Up, Qt.Key_Backspace):
            self.prev_page(animate=animate)
        elif key == Qt.Key_Right:
            self.prev_page(animate=animate) if self.manga_mode else self.next_page(animate=animate)
        elif key == Qt.Key_Left:
            self.next_page(animate=animate) if self.manga_mode else self.prev_page(animate=animate)
        elif key == Qt.Key_PageDown:
            self.next_page(step=1, animate=animate)
        elif key == Qt.Key_PageUp:
            self.prev_page(step=1, animate=animate)
        elif key == Qt.Key_Home:
            self._go_to(0, animate=animate)
        elif key == Qt.Key_End:
            self._go_to(self.total - 1, animate=animate)
        elif key == Qt.Key_D:
            self.toggle_double_page()
        elif key == Qt.Key_M:
            self.toggle_manga_mode()
        elif key == Qt.Key_S:
            self._shift_parity()
        elif key == Qt.Key_F:
            self.cycle_fit_mode()
        elif key == Qt.Key_R:
            self.toggle_smart_crop()
        elif key == Qt.Key_A:
            self.toggle_ambilight()
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self._set_zoom(self.zoom * 1.15)
        elif key == Qt.Key_Minus:
            self._set_zoom(self.zoom / 1.15)
        elif key == Qt.Key_0:
            self._set_zoom(1.0)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            if self._next_volume_path:
                self.next_volume_requested.emit(self._next_volume_path)
        elif key == Qt.Key_C:
            # touche "boss" : masque instantanement la fenetre (reste dans la
            # barre des taches). Ctrl+Alt+C la reaffiche depuis n'importe ou.
            self.window().showMinimized()
        elif key == Qt.Key_Escape:
            self.close_reader()
        else:
            super().keyPressEvent(event)

    def _set_zoom(self, value: float):
        self.zoom = max(0.2, min(6.0, value))
        self._clear_scaled_cache()   # la taille cible change avec le zoom
        self._update_hud()
        self.update()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            self._set_zoom(self.zoom * (1.1 if delta > 0 else 1 / 1.1))
            return
        if event.angleDelta().y() < 0:
            self.next_page()
        else:
            self.prev_page()

    def mousePressEvent(self, event):
        self._show_chrome()
        if event.button() == Qt.BackButton:
            # bouton lateral "page precedente" de la souris : comme Echap,
            # retour a la bibliotheque
            self.close_reader()
            return
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.position().toPoint()
            self._dragged = False

    def mouseMoveEvent(self, event):
        self._show_chrome()
        if self._drag_origin is not None and (event.buttons() & Qt.LeftButton):
            delta = event.position().toPoint() - self._drag_origin
            if self._dragged or delta.manhattanLength() > 6:
                self._dragged = True
                self.pan += delta
                self._drag_origin = event.position().toPoint()
                self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        origin, dragged = self._drag_origin, self._dragged
        self._drag_origin, self._dragged = None, False
        if dragged or origin is None:
            return
        # clic simple : zone gauche/droite -> page precedente/suivante
        # (inverse en mode manga, lecture de droite a gauche)
        if event.position().x() < self.width() * 0.4:
            self.next_page() if self.manga_mode else self.prev_page()
        elif event.position().x() > self.width() * 0.6:
            self.prev_page() if self.manga_mode else self.next_page()

    # ------------------------------------------------------------ fermeture
    def close_reader(self):
        self._save_progress()
        self._persist_reading_pace()
        self.archive.close()
        self.closed.emit()

    def _persist_reading_pace(self):
        """Integre le rythme median de la session au rythme global persiste,
        pour alimenter les estimations de temps de lecture de la bibliotheque."""
        deltas = self._page_deltas()
        if len(deltas) >= TIME_MIN_SAMPLES:
            deltas = sorted(deltas)
            self.store.update_page_seconds(deltas[len(deltas) // 2])
