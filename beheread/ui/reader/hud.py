"""Interface du lecteur : HUD (position, reglages), boutons, barre de pages avec apercu au survol, masquage automatique.

Mixin de ReaderWidget : ces methodes partagent l'etat du lecteur
(self.page, self.cache, self.store...) ; elles sont regroupees ici par
responsabilite."""


from PySide6.QtCore import (
    QSize,
    Qt,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from beheread.ui.reader.components import PageLoader
from beheread.ui.reader.constants import (
    CHROME_HIDE_MS,
    FIT_NAMES,
    HUD_GAP,
    SLIDER_BOTTOM_MARGIN,
    SLIDER_H,
    SLIDER_SIDE_MARGIN,
)


class HudMixin:
    def _place_corner_buttons(self):
        self.back_button.move(14, 14)
        self.fullscreen_button.move(self.width() - self.fullscreen_button.width() - 14, 14)

    def set_fullscreen(self, on: bool):
        """Etat plein ecran de la fenetre du lecteur (voir app.ReaderWindow) :
        le bouton du coin annonce ce qu'il fera."""
        label = "Quitter le plein écran" if on else "Plein écran"
        self.fullscreen_button.setText(" " + label)
        self.fullscreen_button.setAccessibleName(label)
        self.fullscreen_button.adjustSize()
        self._place_corner_buttons()

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
        if self.end_card.isVisible() or self._help.isVisible():
            # ne pas masquer l'interface tant que la fiche de fin est affichee
            self._chrome_timer.start(CHROME_HIDE_MS)
            return
        self._chrome_visible = False
        for w in self._chrome_widgets():
            w.setVisible(False)
        self._hide_preview()
        self.setCursor(Qt.BlankCursor)

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
        if index not in self._preview_loaders and not self.pages.is_pending(index):
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

    # ------------------------------------------------------------ HUD
    def _build_hud(self):
        """Construit le HUD : a gauche un bloc de lecture (position, progression,
        temps restant), a droite une barre de reglages cliquables (chips) qui
        refletent l'etat courant et exposent le raccourci en infobulle. Ces
        reglages valent pour tous les mangas, sauf le sens de lecture, propre
        a chaque serie (l'Ambilight et le fondu se reglent dans les
        preferences)."""
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
            "Afficher deux pages côte à côte   D")
        self.chip_direction = chip(
            "Manga", self.toggle_manga_mode,
            "Lecture de droite à gauche   M")
        self.chip_crop = chip(
            "Recadrage auto", self.toggle_smart_crop,
            "Rogner les marges du scan   R")
        # Selecteur et action ponctuelle : pas des bascules oui/non, style
        # neutre (contour). L'ajustement se lit a son icone : double fleche
        # verticale (hauteur) ou horizontale (largeur).
        self.chip_fit = chip(
            "", self.cycle_fit_mode, "", checkable=False, name="hudSel")
        self.chip_fit.setIconSize(QSize(16, 16))
        self.chip_fit.setAccessibleName("Ajustement")
        self.chip_offset = chip(
            "Décalage", self._shift_parity,
            "Décaler l'appairage des planches   S",
            checkable=False, name="hudSel")

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

        # selecteur d'ajustement : l'icone montre la valeur courante
        self.chip_fit.setIcon(self._fit_icons[self.fit_mode])
        self.chip_fit.setToolTip(FIT_NAMES[self.fit_mode] + " (cliquer pour changer)   F")

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
