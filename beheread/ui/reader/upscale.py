"""Upscaling des pages dans le lecteur : bouton « Upscaling » du HUD,
pages ameliorees affichees a la place des originales, animation de
chargement.

L'option se choisit dans les preferences (Lecture > Amelioration des pages,
desactivee par defaut) ; activee, le bouton apparait dans le HUD (touche U)
et vaut pour la serie, comme les autres reglages du lecteur. Les pages sont
preparees en tache de fond (services/upscaling.py) : en lecture normale,
elles sont pretes avant d'etre affichees. Une page affichee avant d'etre
prete (ouverture du tome, saut) apparait d'abord telle quelle, puis la
version nette la remplace en fondu ; en attendant, un anneau tourne dans le
bouton (HUD visible) ou une petite pastille pulse en bas a droite (HUD
masque).

Mixin de ReaderWidget, comme hud.py ou display.py."""

import math

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from beheread.core import upscale_plan
from beheread.i18n import tr
from beheread.ui.reader.constants import FIT_WIDTH

SPIN_MS = 40           # cadence de l'animation de chargement
SPIN_STEP = 30         # degres par image
PULSE_MS = 1600        # periode de la pulsation de la pastille
BADGE_MARGIN = 24


def spinner_pixmap(size, angle, color, dpr=1.0):
    """Anneau de chargement : un arc plein qui tourne sur un cercle estompe."""
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen_w = max(1.5, size / 7)
    r = QRectF(pen_w / 2, pen_w / 2, size - pen_w, size - pen_w)
    faint = QColor(color)
    faint.setAlphaF(0.25)
    p.setPen(QPen(faint, pen_w))
    p.drawEllipse(r)
    p.setPen(QPen(QColor(color), pen_w, Qt.SolidLine, Qt.RoundCap))
    p.drawArc(r, int(-angle * 16), 100 * 16)
    p.end()
    return pm


class UpscaleBadge(QWidget):
    """Pastille « Amelioration de la page… », affichee quand le HUD est
    masque ; transparente aux clics (la page se tourne au travers)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.angle = 0
        self.phase = 0.0
        self.text = tr("Amélioration de la page…")
        self.colors = {"bg": QColor(20, 22, 26, 200), "border": QColor("#3c4048"),
                       "text": QColor("#d6d9de")}
        self.hide()

    def apply_colors(self, c):
        bg = QColor(c["hud_bg"])
        bg.setAlpha(200)
        self.colors = {"bg": bg, "border": QColor(c["border"]), "text": QColor(c["text"])}
        self._fit()

    def _fit(self):
        fm = self.fontMetrics()
        self.setFixedSize(fm.horizontalAdvance(self.text) + 13 + 8 + 24, fm.height() + 14)

    def place(self):
        parent = self.parentWidget()
        self._fit()
        self.move(parent.width() - self.width() - BADGE_MARGIN,
                  parent.height() - self.height() - BADGE_MARGIN)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(0.55 + 0.45 * (0.5 + 0.5 * math.sin(self.phase)))
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(self.colors["border"], 1))
        p.setBrush(self.colors["bg"])
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        spin = 13
        y = (self.height() - spin) / 2
        p.drawPixmap(QPointF(12, y), spinner_pixmap(spin, self.angle, self.colors["text"],
                                                    self.devicePixelRatioF()))
        p.setPen(self.colors["text"])
        p.drawText(QRect(12 + spin + 8, 0, self.width(), self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.text)
        p.end()


class UpscaleMixin:
    def _build_upscale(self):
        """Etat de l'upscaling, a l'ouverture du lecteur (apres le HUD)."""
        store = self.store
        # option des preferences : sans elle, ni bouton ni traitement
        self.upscale_enabled = bool(store.reader_pref("upscale_enabled", False))
        # choix de la serie (bouton du HUD, touche U), active par defaut
        self.upscale_on = bool(store.reader_setting("upscale", self._series_key, True))
        self._upscale_unavailable = None   # « engine » | « gpu » une fois constate
        self._upscaled = {}                # index -> QImage amelioree, a la taille d'affichage
        self._upscale_skipped = set()      # pages sans besoin (ou en echec)
        self._upscale_service = None
        self._upscale_spin = 0
        self._upscale_timer = QTimer(self)
        self._upscale_timer.setInterval(SPIN_MS)
        self._upscale_timer.timeout.connect(self._step_upscale_spinner)
        self._upscale_badge = UpscaleBadge(self)
        self.chip_upscale.setVisible(self.upscale_enabled)
        if self._upscale_active():
            self._start_upscale_service()

    # ----- etat -----
    def _upscale_active(self):
        return self.upscale_enabled and self.upscale_on and self._upscale_unavailable is None

    def _screen_pixels(self):
        """Taille physique de l'ecran du lecteur : la taille d'affichage des
        pages en plein ecran (et une base stable pour le cache disque, la ou
        la taille de la fenetre varie)."""
        screen = self.screen()
        size = screen.size()
        dpr = screen.devicePixelRatio()
        return round(size.width() * dpr), round(size.height() * dpr)

    def _upscale_needed(self, index):
        """La page en a-t-elle besoin ? None tant qu'elle n'est pas decodee."""
        img = self.cache.get(index)
        if img is None or img.isNull():
            return None
        gain = upscale_plan.display_gain(img.width(), img.height(), *self._screen_pixels(),
                                         self.fit_mode == FIT_WIDTH)
        return upscale_plan.needs_upscale(gain)

    def _upscale_waiting(self):
        """Une page affichee attend encore sa version amelioree (pas une
        page en echec : elle n'arrivera pas ; pas une page en cours de
        decodage : le lecteur affiche deja « Chargement… »)."""
        if not self._upscale_active():
            return False
        return any(i not in self._upscaled and i not in self._upscale_skipped
                   and self._upscale_needed(i)
                   for i in self._current_indices())

    def _upscale_view_sharp(self):
        """Toute la vue s'affiche amelioree : chaque page affichee l'est, ou
        n'en a pas besoin (deja assez grande). Une page en echec garde toute
        la vue en version d'origine : en double page, jamais une page nette
        a cote d'une page floue."""
        return self._upscale_active() and all(
            i in self._upscaled or self._upscale_needed(i) is False
            for i in self._current_indices())

    # ----- service -----
    def _start_upscale_service(self):
        from beheread.services.upscaling import UpscaleService
        key = self.store.key_for(self.path)
        self._upscale_service = UpscaleService(self.archive, key, parent=self)
        self._upscale_service.ready.connect(self._on_upscaled)
        self._upscale_service.skipped.connect(self._on_upscale_skipped)
        self._upscale_service.unavailable.connect(self._on_upscale_unavailable)
        self._request_upscale()

    def _stop_upscale_service(self):
        service, self._upscale_service = self._upscale_service, None
        if service is not None:
            service.stop()
            for sig in (service.ready, service.skipped, service.unavailable):
                sig.disconnect()

    def _request_upscale(self):
        """La vue a change (page, ajustement, double page) : le service
        prepare les pages affichees puis les suivantes ; les pages
        ameliorees trop loin de la vue sont oubliees (memoire bornee)."""
        if self._upscale_service is None:
            return
        from beheread.services.upscaling import hold_window
        current = self._current_indices()
        keep = set(hold_window(current, self.total))
        for index in [i for i in self._upscaled if i not in keep]:
            del self._upscaled[index]
        self._upscale_service.want(current, set(self._upscaled), self._screen_pixels(),
                                   self.fit_mode == FIT_WIDTH)
        self._refresh_upscale_indicator()

    def _on_upscaled(self, index, img):
        from beheread.services.upscaling import hold_window
        if self._upscale_service is None or index not in hold_window(
                self._current_indices(), self.total):
            return
        self._upscaled[index] = img
        self._view_maybe_sharp(index)

    def _view_maybe_sharp(self, index):
        """Une page affichee vient d'etre prete : quand toute la vue l'est
        (les deux pages en double page), elle passe nette d'un seul fondu.
        Jamais une page nette a cote d'une page pas encore prete."""
        shown = self._current_indices()
        if index in shown and self._upscale_view_sharp():
            if self.store.reader_pref("page_fade", True):
                self._start_transition()
            for i in shown:
                self._drop_scaled(i)
            self.update()
        self._refresh_upscale_indicator()

    def _on_upscale_skipped(self, index):
        # sa voisine de double page, deja prete, peut maintenant s'afficher
        self._upscale_skipped.add(index)
        self._view_maybe_sharp(index)

    def _on_upscale_unavailable(self, reason):
        self._upscale_unavailable = reason
        self._stop_upscale_service()
        self._refresh_upscale_indicator()
        self._update_hud()

    def _release_upscale(self):
        self._upscale_timer.stop()
        self._stop_upscale_service()
        self._upscaled.clear()

    # ----- bascule (bouton du HUD, touche U) -----
    def toggle_upscale(self):
        if not self.upscale_enabled or self._upscale_unavailable is not None:
            return
        self.upscale_on = not self.upscale_on
        self.store.set_reader_setting("upscale", self.upscale_on, self._series_key)
        if self.upscale_on:
            self._upscale_skipped.clear()
            self._start_upscale_service()
        else:
            self._stop_upscale_service()
            self._upscaled.clear()
            self._clear_scaled_cache()
        self._refresh_upscale_indicator()
        self._update_hud()
        self.update()

    def _drop_scaled(self, index):
        """Oublie les mises a l'echelle d'une page (sa source a change)."""
        for key in [k for k in self._scaled_cache if k[0] == index]:
            del self._scaled_cache[key]
        self._scaled_order[:] = [k for k in self._scaled_order if k[0] != index]

    def _display_source(self, index, crop):
        """Image a afficher pour la page et son recadrage, ramene a l'echelle
        de la version amelioree (le recadrage est calcule sur l'originale).
        La version amelioree n'est prise que si toute la vue est prete : en
        double page, les deux pages passent nettes ensemble."""
        img = self.cache[index]
        up = self._upscaled.get(index) if self._upscale_active() else None
        if up is None or img.isNull() or img.width() == 0 or not self._upscale_view_sharp():
            return img, crop
        if crop is not None:
            fx, fy = up.width() / img.width(), up.height() / img.height()
            crop = QRect(round(crop.x() * fx), round(crop.y() * fy),
                         round(crop.width() * fx), round(crop.height() * fy))
        return up, crop

    # ----- bouton et animation -----
    def _update_upscale_chip(self):
        chip = self.chip_upscale
        chip.setVisible(self.upscale_enabled)
        if not self.upscale_enabled:
            return
        reason = self._upscale_unavailable
        chip.setEnabled(reason is None)
        chip.setChecked(self.upscale_on and reason is None)
        if reason == "engine":
            chip.setToolTip(tr("Moteur d'upscaling absent de cette installation"))
        elif reason == "gpu":
            chip.setToolTip(tr("Aucun GPU compatible (Vulkan)"))
        else:
            chip.setToolTip(tr("Rendre les pages plus nettes") + "   U")

    def _refresh_upscale_indicator(self):
        """Anime l'anneau du bouton (HUD visible) ou la pastille (HUD masque)
        tant qu'une page affichee attend sa version amelioree."""
        waiting = self._upscale_waiting()
        badge = self._upscale_badge
        if waiting and not self._upscale_timer.isActive():
            self._upscale_timer.start()
        elif not waiting:
            self._upscale_timer.stop()
            if not self.chip_upscale.icon().isNull():
                self.chip_upscale.setIcon(QIcon())
                self._update_hud()
        show_badge = waiting and not self._chrome_visible
        if show_badge:
            badge.place()
            badge.raise_()
        badge.setVisible(show_badge)
        if waiting and self._chrome_visible:
            self._step_upscale_spinner(advance=False)

    def _step_upscale_spinner(self, advance=True):
        if advance:
            self._upscale_spin = (self._upscale_spin + SPIN_STEP) % 360
        if self._chrome_visible:
            had_icon = not self.chip_upscale.icon().isNull()
            color = self._hud_text_color   # couleur du texte du bouton (apply_theme)
            self.chip_upscale.setIconSize(QSize(14, 14))
            self.chip_upscale.setIcon(QIcon(spinner_pixmap(
                14, self._upscale_spin, color, self.devicePixelRatioF())))
            if not had_icon:   # le bouton s'elargit : la barre se recale
                self._update_hud()
        else:
            badge = self._upscale_badge
            badge.angle = self._upscale_spin
            badge.phase = (badge.phase + 2 * math.pi * SPIN_MS / PULSE_MS) % (2 * math.pi)
            badge.update()
