"""Entrees du lecteur : clavier, molette / pave tactile, souris.

Mixin de ReaderWidget : ces methodes partagent l'etat du lecteur
(self.page, self.cache, self.store...) ; elles sont regroupees ici par
responsabilite."""

import time

from PySide6.QtCore import (
    QPoint,
    Qt,
)


class InputMixin:
    # ------------------------------------------------------------ entrees
    def _toggle_help(self):
        self._help.toggle()
        self._show_chrome()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_F1, Qt.Key_Question):
            self._toggle_help()
            return
        if self._help.isVisible():
            # n'importe quelle touche ferme l'aide ; Echap ne fait QUE la fermer
            # (sans quitter le lecteur)
            self._help.hide()
            if key == Qt.Key_Escape:
                return
        # touche maintenue (auto-repeat) : on saute le fondu pour ne pas
        # empiler les transitions et effondrer les perfs en navigation rapide.
        animate = not event.isAutoRepeat()
        if key in (Qt.Key_Down, Qt.Key_Space):
            # page plus haute que l'ecran : on la fait d'abord defiler
            if not self._scroll_within_page(-0.85 * self.height()):
                self.next_page(animate=animate)
        elif key == Qt.Key_Up:
            if not self._scroll_within_page(0.85 * self.height()):
                self.prev_page(animate=animate, align="bottom")
        elif key == Qt.Key_Backspace:
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
        elif key == Qt.Key_C and self.store.reader_pref("boss_key", True):
            # touche "boss" : masque instantanement la fenetre (reste dans la
            # barre des taches). Ctrl+Alt+C la reaffiche depuis n'importe ou.
            self.window().showMinimized()
        elif key == Qt.Key_Escape:
            self.close_reader()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self._set_zoom(self.zoom * (1.1 if delta > 0 else 1 / 1.1))
            event.accept()
            return
        # molette / pave tactile : defilement dans une page qui depasse, puis
        # tour de page au bord (logique pure dans wheel_nav.py)
        touchpad = not event.pixelDelta().isNull()
        dy = event.pixelDelta().y() if touchpad else event.angleDelta().y()
        action = self._wheel.feed(dy, touchpad, time.monotonic(),
                                  self._scroll_within_page)
        if action == "next":
            self.next_page()
        elif action == "prev":
            self.prev_page(align="bottom")
        event.accept()

    def _scroll_within_page(self, px) -> bool:
        """Fait defiler verticalement de `px` pixels (negatif = vers le bas)
        une page plus haute que l'ecran. Renvoie False si la page tient dans
        l'ecran ou si elle est deja au bord dans ce sens (l'appelant tourne
        alors la page)."""
        if self._view_geom is None:
            return False
        y, h, vh = self._view_geom
        if h <= vh + 1:
            return False
        new_y = min(0.0, max(vh - h, y + px))
        if abs(new_y - y) < 0.5:
            return False
        self.pan = QPoint(self.pan.x(), self.pan.y() + round(new_y - y))
        self._view_geom = (new_y, h, vh)
        self.update()
        return True

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
