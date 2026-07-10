"""Delegates de rendu de la bibliotheque : grille (vignettes avec pile de
couvertures pour les series) et liste compacte. Ils ne lisent que les donnees
portees par l'index (roles ROLE_*), sans connaitre le widget."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

import theme
from lib_constants import (CELL_H, CELL_W, HEADER_H, LIST_ROW_H, LIST_THUMB_H,
                           LIST_THUMB_W, ROLE_AUTHOR_TEXT, ROLE_FINISHED,
                           ROLE_FRACTION, ROLE_IS_HEADER, ROLE_IS_SERIES,
                           ROLE_PIXMAP, ROLE_PIXMAP2, ROLE_PIXMAP3,
                           ROLE_PROG_TEXT, ROLE_SERIES_COUNT, STACK_PEEK,
                           THUMB_H, THUMB_W)
from storage import Store


def _cover_source_rect(pm: QPixmap, target: QSize) -> QRect:
    """Sous-rectangle (recadrage centre) de la couverture haute resolution pm
    ayant le MEME rapport largeur/hauteur que `target`, a passer a
    drawPixmap(targetRect, pm, source). drawPixmap met ensuite ce sous-rect a
    l'echelle de targetRect : la couverture remplit exactement la cible sans
    deformation, et - la source restant en pleine resolution - le rendu reste
    net a n'importe quelle taille d'affichage (le curseur de taille change
    targetRect, pas le cache). pm est en pixels physiques (dpr=1) ; le
    redimensionnement final vers les pixels-ecran est fait par le painter."""
    pw, ph = pm.width(), pm.height()
    tw, th = target.width(), target.height()
    if pw <= 0 or ph <= 0 or tw <= 0 or th <= 0:
        return QRect(0, 0, pw, ph)
    if pw * th > ph * tw:          # pm plus large que la cible -> rogne les cotes
        nw = max(1, round(ph * tw / th))
        return QRect((pw - nw) // 2, 0, nw, ph)
    nh = max(1, round(pw * th / tw))   # pm plus haut -> rogne haut/bas
    return QRect(0, (ph - nh) // 2, pw, nh)


class MangaDelegate(QStyledItemDelegate):
    """Dessine la vignette, le titre, la barre de progression et le badge.
    La taille des couvertures est pilotee par un facteur d'echelle (curseur de
    la barre d'outils) : seule la couverture grandit, la legende garde sa
    hauteur pour rester lisible."""

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.set_scale(1.0)

    def set_scale(self, scale: float):
        """Recalcule les dimensions de case/vignette pour le facteur donne."""
        self.scale = scale
        self.thumb_w = round(THUMB_W * scale)
        self.thumb_h = round(THUMB_H * scale)
        self.cell_w = self.thumb_w + (CELL_W - THUMB_W)   # + marges laterales fixes
        self.cell_h = self.thumb_h + (CELL_H - THUMB_H)   # + hauteur de legende fixe

    def sizeHint(self, option, index):
        return QSize(self.cell_w, self.cell_h)

    def paint(self, painter: QPainter, option, index):
        c = theme.colors(self.store.ui_pref("theme", "dark"))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        r = option.rect

        if option.state & QStyle.State_Selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(c["selection"]))
            painter.drawRoundedRect(r.adjusted(2, 2, -2, -2), 10, 10)

        if index.data(ROLE_IS_SERIES):
            self._paint_series(painter, option, index, c)
            painter.restore()
            return

        finished = bool(index.data(ROLE_FINISHED))
        if finished:
            # grise legerement la couverture et le titre pour distinguer
            # les mangas termines, sans affecter la barre/le badge plus bas
            painter.setOpacity(0.55)

        # cadre de la couverture
        cover = QRect(r.x() + (r.width() - self.thumb_w) // 2, r.y() + 10,
                      self.thumb_w, self.thumb_h)
        path = QPainterPath()
        path.addRoundedRect(cover, 6, 6)
        painter.setClipPath(path)
        # pm est la couverture haute resolution ; drawPixmap la met a l'echelle
        # de la case courante (voir _cover_source_rect). Le curseur de taille
        # change donc la taille sans toucher au cache.
        pm: QPixmap = index.data(ROLE_PIXMAP)
        if pm and not pm.isNull():
            painter.drawPixmap(cover, pm, _cover_source_rect(pm, cover.size()))
        else:
            painter.fillRect(cover, QColor(c["cover_placeholder"]))
            painter.setPen(QColor(c["cover_text"]))
            painter.drawText(cover, Qt.AlignCenter, "...")
        painter.setClipping(False)
        painter.setPen(QPen(QColor(c["cover_border"]), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(cover, 6, 6)

        painter.setOpacity(1.0)

        # barre de progression
        frac = index.data(ROLE_FRACTION) or 0.0
        if finished or frac > 0:
            bar = QRect(cover.x(), cover.bottom() - 5, cover.width(), 6)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(c["track_bg"]))
            painter.drawRect(bar)
            color = QColor(theme.FINISHED) if finished else QColor(theme.ACCENT)
            w = bar.width() if finished else max(3, int(bar.width() * frac))
            painter.setBrush(color)
            painter.drawRect(QRect(bar.x(), bar.y(), w, bar.height()))

        if finished:
            self._draw_finished_badge(painter, cover)

        # titre + progression + auteur (bloc commun aux tomes et aux series)
        if finished:
            painter.setOpacity(0.55)
        self._draw_caption(painter, option, index, c, cover.bottom() + 8, r)

        painter.restore()

    # ----- blocs communs (tome simple / dossier de serie) -----
    @staticmethod
    def _draw_finished_badge(painter, cover):
        """Pastille verte "termine" (coche) en haut a droite de la couverture."""
        badge = QRect(cover.right() - 26, cover.y() + 6, 20, 20)
        painter.setBrush(QColor(theme.FINISHED))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(badge)
        painter.setPen(QPen(QColor("#10251a"), 2))
        painter.drawLine(badge.x() + 5, badge.y() + 10, badge.x() + 9, badge.y() + 14)
        painter.drawLine(badge.x() + 9, badge.y() + 14, badge.x() + 15, badge.y() + 6)

    def _draw_caption(self, painter, option, index, c, top, r):
        """Titre (elide), texte de progression et auteur sous la couverture -
        identiques pour un tome et pour un dossier de serie."""
        title_rect = QRect(r.x() + 6, top, r.width() - 12, 34)
        painter.setPen(QColor(c["text"]))
        f = QFont(option.font)
        f.setPointSizeF(f.pointSizeF() * 0.95)
        painter.setFont(f)
        fm = painter.fontMetrics()
        name = index.data(Qt.DisplayRole) or ""
        painter.drawText(title_rect, Qt.AlignHCenter | Qt.AlignTop,
                         fm.elidedText(name, Qt.ElideRight, title_rect.width()))

        prog_text = index.data(ROLE_PROG_TEXT)
        if prog_text:
            painter.setPen(QColor(c["text_dim"]))
            painter.drawText(QRect(title_rect.x(), title_rect.y() + 16,
                                   title_rect.width(), 16),
                             Qt.AlignHCenter | Qt.AlignTop, prog_text)

        author_text = index.data(ROLE_AUTHOR_TEXT)
        if author_text:
            painter.setPen(QColor(c["text_dim"]))
            fa = QFont(option.font)
            fa.setPointSizeF(fa.pointSizeF() * 0.85)
            painter.setFont(fa)
            fma = painter.fontMetrics()
            painter.drawText(QRect(title_rect.x(), title_rect.y() + 32,
                                   title_rect.width(), 16),
                             Qt.AlignHCenter | Qt.AlignTop,
                             fma.elidedText(author_text, Qt.ElideRight, title_rect.width()))

    # ----- rendu d'un dossier de serie (couvertures empilees) -----
    def _draw_cover_layer(self, painter, rect, pm, c, opacity=1.0):
        """Dessine une couverture (ou un placeholder) dans un cadre arrondi,
        rognee au centre - une couche de la pile d'un dossier de serie."""
        painter.setOpacity(opacity)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.save()
        painter.setClipPath(path)
        if pm and not pm.isNull():
            painter.drawPixmap(rect, pm, _cover_source_rect(pm, rect.size()))
        else:
            painter.fillRect(rect, QColor(c["cover_placeholder"]))
        painter.restore()
        painter.setPen(QPen(QColor(c["cover_border"]), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 6, 6)
        painter.setOpacity(1.0)

    def _paint_series(self, painter, option, index, c):
        r = option.rect
        finished = bool(index.data(ROLE_FINISHED))

        pms = [index.data(ROLE_PIXMAP), index.data(ROLE_PIXMAP2),
               index.data(ROLE_PIXMAP3)]
        pms = [pm for pm in pms if pm and not pm.isNull()]
        layers = max(1, min(3, len(pms) or 1))   # au moins 1 couche (placeholder)

        # la pile occupe la meme empreinte qu'une couverture simple, les
        # couches arriere debordant en bas a droite. On reduit donc la
        # couverture de tete de (layers-1)*peek pour que l'ensemble reste
        # aligne sur les vignettes des tomes simples.
        peek = STACK_PEEK
        shrink = (layers - 1) * peek
        fw, fh = self.thumb_w - shrink, self.thumb_h - shrink
        gx = r.x() + (r.width() - self.thumb_w) // 2
        gy = r.y() + 10

        if finished:
            painter.setOpacity(0.55)

        # couches arriere -> avant. La couche de tete (front) porte la
        # couverture du 1er tome ; les couches derriere sont assombries.
        for i in range(layers - 1, -1, -1):
            rect = QRect(gx + i * peek, gy + i * peek, fw, fh)
            pm = pms[i] if i < len(pms) else None
            self._draw_cover_layer(painter, rect, pm, c,
                                   opacity=1.0 if i == 0 else 0.82)

        front = QRect(gx, gy, fw, fh)

        painter.setOpacity(1.0)

        # pastille "N tomes" en haut a gauche de la couverture de tete
        count = index.data(ROLE_SERIES_COUNT) or 0
        label = f"{count}"
        f = QFont(option.font)
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 0.95)
        painter.setFont(f)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(label)
        chip = QRect(front.x() + 8, front.y() + 8, max(22, tw + 14), 22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ACCENT))
        painter.drawRoundedRect(chip, 11, 11)
        painter.setPen(QColor("#f5f0ee"))
        painter.drawText(chip, Qt.AlignCenter, label)

        if finished:
            self._draw_finished_badge(painter, front)
            painter.setOpacity(0.55)

        # titre de la serie + progression + auteur (bloc commun avec les tomes)
        stack_bottom = gy + fh + (layers - 1) * peek
        self._draw_caption(painter, option, index, c, stack_bottom + 8, r)


class ListDelegate(QStyledItemDelegate):
    """Rendu compact en ligne, avec en-tetes de serie non selectionnables."""

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store

    def sizeHint(self, option, index):
        if index.data(ROLE_IS_HEADER):
            return QSize(0, HEADER_H)
        return QSize(0, LIST_ROW_H)

    def paint(self, painter: QPainter, option, index):
        c = theme.colors(self.store.ui_pref("theme", "dark"))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        r = option.rect

        if index.data(ROLE_IS_HEADER):
            painter.fillRect(r, QColor(c["header_bg"]))
            painter.setPen(QColor(c["text_dim"]))
            f = QFont(option.font)
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() * 0.9)
            painter.setFont(f)
            painter.drawText(r.adjusted(12, 0, -12, 0), Qt.AlignVCenter | Qt.AlignLeft,
                             index.data(Qt.DisplayRole) or "")
            painter.setPen(QColor(c["border"]))
            painter.drawLine(r.bottomLeft(), r.bottomRight())
            painter.restore()
            return

        if option.state & QStyle.State_Selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(c["selection"]))
            painter.drawRect(r)

        finished = bool(index.data(ROLE_FINISHED))
        if finished:
            painter.setOpacity(0.55)

        is_series = bool(index.data(ROLE_IS_SERIES))
        thumb = QRect(r.x() + 10, r.y() + (r.height() - LIST_THUMB_H) // 2,
                      LIST_THUMB_W, LIST_THUMB_H)
        if is_series:
            # petit empilement derriere la vignette pour signaler un dossier
            thumb = QRect(thumb.x(), thumb.y(), thumb.width() - 6, thumb.height() - 6)
            for i in (2, 1):
                back = thumb.translated(i * 3, i * 3)
                painter.setPen(QPen(QColor(c["cover_border"]), 1))
                painter.setBrush(QColor(c["cover_placeholder"]))
                painter.drawRoundedRect(back, 4, 4)
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 4, 4)
        painter.setClipPath(clip)
        pm = index.data(ROLE_PIXMAP)
        if pm and not pm.isNull():
            # meme couverture haute resolution que la grille : drawPixmap la
            # met a l'echelle de la petite vignette de liste (voir
            # _cover_source_rect), rendu net sans pre-redimensionnement.
            painter.drawPixmap(thumb, pm, _cover_source_rect(pm, thumb.size()))
        else:
            painter.fillRect(thumb, QColor(c["cover_placeholder"]))
        painter.setClipping(False)

        text_x = thumb.right() + 14
        text_w = max(40, r.width() - text_x - 90)

        title_rect = QRect(text_x, r.y() + 9, text_w, 20)
        painter.setPen(QColor(c["text"]))
        painter.setFont(QFont(option.font))
        fm = painter.fontMetrics()
        name = index.data(Qt.DisplayRole) or ""
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         fm.elidedText(name, Qt.ElideRight, title_rect.width()))

        # en vue liste (compacte), progression et auteur partagent la meme
        # ligne de sous-titre plutot que d'ajouter une ligne supplementaire
        prog_text = index.data(ROLE_PROG_TEXT)
        author_text = index.data(ROLE_AUTHOR_TEXT)
        subtitle = "  ·  ".join(t for t in (prog_text, author_text) if t)
        if subtitle:
            painter.setPen(QColor(c["text_dim"]))
            sub_rect = QRect(text_x, r.y() + 32, text_w, 18)
            painter.drawText(sub_rect, Qt.AlignLeft | Qt.AlignVCenter,
                             fm.elidedText(subtitle, Qt.ElideRight, sub_rect.width()))

        painter.setOpacity(1.0)
        if is_series:
            # chevron ">" a droite : indique qu'on entre dans le dossier
            cx, cy = r.right() - 20, r.y() + r.height() // 2
            painter.setPen(QPen(QColor(c["text_dim"]), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolyline([QPoint(cx - 4, cy - 6), QPoint(cx + 4, cy),
                                  QPoint(cx - 4, cy + 6)])
        else:
            frac = index.data(ROLE_FRACTION) or 0.0
            if finished or frac > 0:
                bar_w = 70
                bar = QRect(r.right() - bar_w - 14, r.y() + r.height() // 2 - 3, bar_w, 6)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(c["track_bg"]))
                painter.drawRect(bar)
                color = QColor(theme.FINISHED) if finished else QColor(theme.ACCENT)
                w = bar.width() if finished else max(2, int(bar.width() * frac))
                painter.setBrush(color)
                painter.drawRect(QRect(bar.x(), bar.y(), w, bar.height()))

        painter.restore()
