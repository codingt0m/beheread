"""Vues de base de la bibliotheque : liste a defilement doux (grille
centree) et conteneur cliquable (logo de l'en-tete)."""

from PySide6.QtCore import QEasingCurve, QEvent, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QListWidget, QWidget


class _TopFade(QWidget):
    """Degrade pose sur le haut de la grille : les couvertures qui remontent
    sous la barre de filtres s'y fondent au lieu d'etre coupees net.
    Transparent pour la souris."""

    HEIGHT = 36

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.color = QColor("#1b1e24")
        self.strength = 0.0   # 0 = invisible (grille en haut), 1 = degrade complet

    def paintEvent(self, _event):
        if self.strength <= 0:
            return
        top = QColor(self.color)
        top.setAlphaF(0.95 * self.strength)
        clear = QColor(self.color)
        clear.setAlphaF(0.0)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, clear)
        QPainter(self).fillRect(self.rect(), grad)


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
        self.host = None   # ScrollingHeaderHost eventuel (en-tete qui defile avec la liste)
        self._wheel_anim = QVariantAnimation(self)
        self._wheel_anim.setDuration(140)
        self._wheel_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._wheel_anim.valueChanged.connect(lambda v: self._set_position(int(v)))
        self._top_fade = _TopFade(self)
        self.verticalScrollBar().valueChanged.connect(self._update_top_fade)

    # position de defilement globale : en-tete eventuel + barre de defilement
    def _position(self):
        return self.host.position() if self.host else self.verticalScrollBar().value()

    def _max_position(self):
        return self.host.max_position() if self.host else self.verticalScrollBar().maximum()

    def _set_position(self, value):
        if self.host:
            self.host.set_position(value)
        else:
            self.verticalScrollBar().setValue(value)

    def set_fade_color(self, color):
        """Couleur du fond de la grille (theme), dans laquelle le haut se fond."""
        self._top_fade.color = QColor(color)
        self._top_fade.update()

    def _place_top_fade(self):
        # sur toute la largeur de la grille, marges de centrage comprises,
        # sans recouvrir la barre de defilement
        vp = self.viewport().geometry()
        right = vp.right() + self.viewportMargins().right()
        self._top_fade.setGeometry(0, vp.top(), right + 1, _TopFade.HEIGHT)
        self._top_fade.raise_()

    def _update_top_fade(self, value=None):
        # le degrade apparait progressivement des qu'on a defile : grille en
        # haut, rien n'est coupe et la premiere rangee reste nette
        value = self.verticalScrollBar().value() if value is None else value
        strength = min(1.0, max(0, value) / _TopFade.HEIGHT)
        if strength != self._top_fade.strength:
            self._top_fade.strength = strength
            self._top_fade.update()

    def wheelEvent(self, event):
        if not event.pixelDelta().isNull():
            # pave tactile : defilement direct, sans animation
            self._wheel_anim.stop()
            self._set_position(self._position() - event.pixelDelta().y())
            event.accept()
            return
        steps = event.angleDelta().y() / 120.0
        # si une animation est en cours, on enchaine depuis sa cible pour que
        # les crans rapides s'accumulent au lieu de repartir de la position
        # courante (ce qui "avalerait" une partie du defilement)
        if self._wheel_anim.state() == QVariantAnimation.Running:
            base = self._wheel_anim.endValue()
        else:
            base = self._position()
        target = max(0, min(self._max_position(), base - steps * self.WHEEL_STEP))
        self._wheel_anim.stop()
        # les deux bornes doivent etre du meme type : QVariantAnimation ne
        # sait pas interpoler entre un int et un float (elle n'emet alors
        # aucune valeur et le scroll semble mort)
        self._wheel_anim.setStartValue(float(self._position()))
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
        self._place_top_fade()

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
            self._place_top_fade()


class ScrollingHeaderHost(QWidget):
    """Empile un en-tete (bande « Continuer la lecture ») au-dessus d'une
    SmoothListWidget et le fait defiler avec elle, comme s'il etait le debut
    de la grille : le defilement consomme d'abord la hauteur de l'en-tete
    (qui remonte hors de vue, la liste montant d'autant), puis fait defiler
    la liste. La liste garde sa propre barre et sa hauteur pleine : seuls des
    deplacements de widgets, aucun redimensionnement (donc aucune remise en
    page de la grille) pendant le defilement."""

    def __init__(self, header, view, parent=None):
        super().__init__(parent)
        self.header, self.view = header, view
        header.setParent(self)
        view.setParent(self)
        view.host = self
        self._offset = 0         # pixels d'en-tete deja remontes hors de vue
        self._applying = False   # la barre bouge du fait de set_position
        header.installEventFilter(self)
        view.verticalScrollBar().valueChanged.connect(self._on_list_scrolled)

    def _extent(self):
        return 0 if self.header.isHidden() else self.header.sizeHint().height()

    def position(self):
        return self._offset + self.view.verticalScrollBar().value()

    def max_position(self):
        return self._extent() + self.view.verticalScrollBar().maximum()

    def set_position(self, value):
        value = max(0, min(int(value), self.max_position()))
        extent = self._extent()
        self._applying = True
        try:
            self.view.verticalScrollBar().setValue(max(0, value - extent))
        finally:
            self._applying = False
        self._offset = min(value, extent)
        self._relayout()

    def _on_list_scrolled(self, value):
        # defilement venu d'ailleurs (clavier, barre, scrollToTop,
        # restauration de position) : liste defilee -> en-tete hors de vue,
        # liste revenue en haut -> en-tete de nouveau visible
        if not self._applying:
            self._offset = self._extent() if value > 0 else 0
            self._relayout()

    def _relayout(self):
        extent = self._extent()
        if self.view.verticalScrollBar().value() > 0:
            self._offset = extent
        self._offset = min(self._offset, extent)
        w, h = self.width(), self.height()
        self.header.setGeometry(0, -self._offset, w, extent)
        self.view.setGeometry(0, extent - self._offset, w, h)

    def eventFilter(self, obj, event):
        if obj is self.header and event.type() in (
                QEvent.ShowToParent, QEvent.HideToParent, QEvent.LayoutRequest):
            self._relayout()
        return False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()


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
