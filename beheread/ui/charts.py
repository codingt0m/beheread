"""Composants graphiques des statistiques de lecture (voir stats_view.py,
qui les assemble) : tuiles de chiffres, histogramme, classement,
calendrier, liste des tomes termines, barre de repartition, cartes.

Choix de visualisation : voir l'en-tete de stats_view.py."""


from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from beheread.core import stats
from beheread.i18n import N_, fmt_decimal, fmt_int, tr, trn
from beheread.ui import theme

# couleurs de donnees (validees avec le script de la methode dataviz)
_GREEN, _TEAL, _VIOLET, _AMBER, _PINK = "#3fa35f", "#1f9d9a", "#8a63d2", "#bd8215", "#d6457f"
_PURPLE = "#8f33cc"
_BLUE = {"dark": "#3987e5", "light": "#2a78d6"}


def data_colors(mode) -> dict:
    """Couleurs des graphiques pour l'accent courant. L'activite de lecture
    porte l'accent ; « termines » (vert) et « non lus » (bleu) prennent une
    autre couleur de la liste quand l'accent choisi s'en approche trop, pour
    que les trois parts de la repartition restent distinctes. Avec l'accent
    par defaut : vert et bleu."""
    blue = _BLUE["light" if mode == "light" else "dark"]
    accent = theme.ACCENT
    pairs = [(f, u) for f in (_GREEN, blue, _TEAL, _VIOLET, _AMBER, _PINK, _PURPLE)
             for u in (blue, _VIOLET, _AMBER, _PINK, _TEAL, _PURPLE, _GREEN) if f != u]

    def margin(pair):
        # dans la barre empilee, « en cours » (accent) separe les deux autres
        # parts : elles ne se touchent jamais, la vision normale suffit
        f, u = pair
        return min(theme.separation(f, accent), theme.separation(u, accent),
                   theme.separation(f, u, cvd=False))
    finished, unread = (next((p for p in pairs if margin(p) >= 1), None)
                        or max(pairs, key=margin))
    return {"activity": accent, "reading": accent, "finished": finished, "unread": unread}

# noms abreges, traduits a l'affichage (voir month_name et day_name)
MONTHS_FR = [N_("janv."), N_("févr."), N_("mars"), N_("avr."), N_("mai"), N_("juin"),
             N_("juil."), N_("août"), N_("sept."), N_("oct."), N_("nov."), N_("déc.")]
DAYS_FR = [N_("lun."), N_("mar."), N_("mer."), N_("jeu."), N_("ven."), N_("sam."), N_("dim.")]


def month_name(month) -> str:
    """Nom abrege du mois (1 a 12) dans la langue de l'interface."""
    return tr(MONTHS_FR[month - 1])


def day_name(weekday) -> str:
    """Nom abrege du jour (0 = lundi) dans la langue de l'interface."""
    return tr(DAYS_FR[weekday])


def _fmt_int(n) -> str:
    return fmt_int(n)


def fmt_day(d, year=True) -> str:
    """« 1er oct. 2026 », « 14 nov. » sans l'annee."""
    day = tr("1er") if d.day == 1 else str(d.day)
    if year:
        return tr("{day} {month} {year}", day=day, month=month_name(d.month), year=d.year)
    return tr("{day} {month}", day=day, month=month_name(d.month))


def fmt_pace(seconds) -> str:
    text = f"{seconds:.0f}" if seconds >= 10 else fmt_decimal(seconds)
    return tr("{seconds} s par page", seconds=text)


def fmt_estimate(seconds) -> str:
    """Duree estimee : au-dela de dix heures, les minutes n'ont pas de sens."""
    if seconds >= 36000:
        return f"{_fmt_int(round(seconds / 3600))} h"
    return stats.fmt_duration(seconds, compact=True)


def _small_font(widget) -> QFont:
    font = QFont(widget.font())
    font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
    return font


# ---------------------------------------------------------------- briques

class Sparkline(QWidget):
    """Mini-tendance d'une tuile : une barre par jour ou par mois, sans axe
    ni valeur. Teinte de retrait, sauf la derniere barre (jour ou mois en
    cours), dans la couleur de la mesure."""

    HEIGHT = 26

    def __init__(self, color, colors):
        super().__init__()
        self.values = []
        self.color = QColor(color)
        self.c = colors
        self.setFixedHeight(self.HEIGHT)

    def set_values(self, values):
        self.values = list(values)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.setPen(QPen(theme.qcolor(self.c["border"]), 1))
        p.drawLine(QPoint(0, h - 1), QPoint(w, h - 1))
        n = len(self.values)
        peak = max(self.values, default=0)
        if n and peak > 0:
            slot = w / n
            bw = max(1.0, min(8.0, slot - 1))
            dim = QColor(self.c["text_dim"])
            dim.setAlpha(120)
            p.setPen(Qt.NoPen)
            for i, value in enumerate(self.values):
                if value <= 0:
                    continue
                bh = max(2.0, (h - 2) * value / peak)
                p.setBrush(self.color if i == n - 1 else dim)
                p.drawRect(QRectF(i * slot + (slot - bw) / 2, h - 1 - bh, bw, bh))
        p.end()


class Meter(QWidget):
    """Jauge d'un ratio (jours de lecture sur jours de la periode) : la piste
    est une nuance plus claire de la meme teinte."""

    def __init__(self, color):
        super().__init__()
        self.color = QColor(color)
        self.ratio = 0.0
        self.setFixedHeight(Sparkline.HEIGHT)

    def set_ratio(self, ratio):
        self.ratio = max(0.0, min(1.0, float(ratio)))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QColor(self.color)
        track.setAlpha(55)
        bar = QRectF(0, self.height() - 9, self.width(), 6)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(bar, 3, 3)
        if self.ratio > 0:
            p.setBrush(self.color)
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), max(6.0, bar.width() * self.ratio),
                                     bar.height()), 3, 3)
        p.end()


class StatTile(QFrame):
    """Chiffre cle : libelle, valeur, ecart a la periode precedente (`delta`,
    court : la periode comparee est nommee une fois, en tete de fenetre),
    mini-graphique (`viz`) et precision (`sub`). `hero` : chiffre principal."""

    def __init__(self, label, viz=None, hero=False):
        super().__init__()
        self.setObjectName("tile")
        self.label = label
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(2)
        lab = self._label = QLabel(label)
        lab.setObjectName("tileLabel")
        self.value = QLabel()
        self.value.setObjectName("heroValue" if hero else "tileValue")
        self.delta = QLabel()
        self.delta.setObjectName("tileDelta")
        self.sub = QLabel()
        self.sub.setObjectName("tileSub")
        self.sub.setWordWrap(True)
        v.addWidget(lab)
        v.addWidget(self.value)
        v.addWidget(self.delta)
        v.addStretch(1)
        if viz is not None:
            v.addWidget(viz)
        v.addWidget(self.sub)

    def set_label(self, label):
        self.label = label
        self._label.setText(label)

    def set_content(self, value, delta="", sub="", tip=""):
        self.value.setText(value)
        self.delta.setText(delta)
        self.delta.setVisible(bool(delta))
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        self.setToolTip(tip)
        self.setAccessibleName(" - ".join(
            t for t in (tr("{label} : {value}", label=self.label, value=value), delta, sub) if t))


class BarChart(QWidget):
    """Histogramme vertical a une serie. bars : [(etiquette d'axe ou "",
    valeur, texte d'infobulle)]. Sous les etiquettes d'axe, des lignes de
    notes facultatives (une valeur par barre, voir set_bars)."""

    BAR_MAX = 24
    GAP = 2
    LEFT, RIGHT, TOP, BOTTOM = 52, 8, 22, 26
    NOTE_H = 16

    def __init__(self, color, colors, value_fmt=_fmt_int, empty_text="",
                 ticks=stats.nice_ticks, height=150, label_all=False, bar_max=BAR_MAX):
        """`ticks` : fonction (maximum) -> graduations de l'axe des valeurs.
        `label_all` : la valeur au-dessus de chaque barre (quand elle tient),
        pas seulement de la plus haute."""
        super().__init__()
        self.bars = []
        self.notes = []
        self.label_all = label_all
        self.bar_max = bar_max
        self.base_height = height
        self.color = QColor(color)
        self.c = colors
        self.value_fmt = value_fmt
        self.empty_text = empty_text
        self.tick_fn = ticks
        self.ticks = ticks(0)
        self.hover = -1
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(height)

    reference = None    # (valeur, libelle) : trait de repere horizontal (mediane...)

    def set_bars(self, bars, reference=None, notes=()):
        """notes : [(legende, [texte par barre], couleur ou None)], une ligne
        chacune sous les etiquettes d'axe, sa legende dans la marge gauche."""
        self.bars = list(bars)
        self.notes = list(notes)
        self.setMinimumHeight(self.base_height + self.NOTE_H * len(self.notes))
        self.reference = reference if reference and reference[0] > 0 else None
        self.ticks = self.tick_fn(max((b[1] for b in self.bars), default=0))
        self.hover = -1
        self.update()

    def sizeHint(self):
        return QSize(420, self.minimumHeight() + 10)

    def _plot(self):
        bottom = self.BOTTOM + self.NOTE_H * len(self.notes)
        return QRect(self.LEFT, self.TOP, self.width() - self.LEFT - self.RIGHT,
                     self.height() - self.TOP - bottom)

    def _slot(self, i):
        plot = self._plot()
        w = plot.width() / max(1, len(self.bars))
        return QRectF(plot.left() + i * w, plot.top(), w, plot.height())

    def _bar_rect(self, i):
        plot = self._plot()
        slot = self._slot(i)
        bw = max(2.0, min(self.bar_max, slot.width() - self.GAP))
        top_value = self.ticks[-1] or 1
        h = plot.height() * (self.bars[i][1] / top_value)
        return QRectF(slot.center().x() - bw / 2, plot.bottom() + 1 - h, bw, h)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        plot = self._plot()
        grid = theme.qcolor(self.c["border"])
        text_dim = QColor(self.c["text_dim"])
        p.setFont(_small_font(self))
        fm = p.fontMetrics()
        top_value = self.ticks[-1] or 1

        # grille horizontale + graduations (traits fins pleins)
        for t in self.ticks:
            y = plot.bottom() - plot.height() * (t / top_value)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPoint(plot.left(), round(y)), QPoint(plot.right(), round(y)))
            p.setPen(text_dim)
            p.drawText(QRect(0, round(y) - 8, self.LEFT - 8, 16),
                       Qt.AlignRight | Qt.AlignVCenter, self.value_fmt(t))

        if not any(b[1] for b in self.bars):
            p.setPen(text_dim)
            p.drawText(plot, Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)
        peak_i = max(range(len(self.bars)), key=lambda i: self.bars[i][1]) if self.bars else -1
        shown = self._visible_labels(fm)
        for i, (label, value, _tip) in enumerate(self.bars):
            if value > 0:
                r = self._bar_rect(i)
                color = QColor(self.color)
                if i == self.hover:
                    color = color.lighter(125)
                path = QPainterPath()
                path.setFillRule(Qt.WindingFill)   # formes superposees : union, pas de trous
                radius = min(4.0, r.width() / 2, r.height())
                path.addRoundedRect(r, radius, radius)
                # base carree : on recouvre les coins arrondis du bas
                path.addRect(QRectF(r.left(), r.bottom() - radius, r.width(), radius))
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawPath(path.simplified())
                txt = self.value_fmt(value)
                tw = fm.horizontalAdvance(txt)
                if i == peak_i or (self.label_all and tw + 4 <= self._slot(i).width()):
                    p.setPen(QColor(self.c["text"]))
                    x = max(plot.left(), min(plot.right() - tw - 4, r.center().x() - tw / 2 - 2))
                    p.drawText(QRectF(x, r.top() - 18, tw + 4, 16), Qt.AlignCenter, txt)
            if i in shown:
                slot = self._slot(i)
                tw = fm.horizontalAdvance(label)
                p.setPen(text_dim)
                p.drawText(QRectF(slot.center().x() - tw / 2 - 2, plot.bottom() + 6, tw + 4, 16),
                           Qt.AlignCenter, label)
        for row, (caption, texts, color) in enumerate(self.notes):
            y = plot.bottom() + 6 + self.BOTTOM - 8 + row * self.NOTE_H
            p.setPen(text_dim)
            p.drawText(QRect(0, round(y), self.LEFT - 8, 16), Qt.AlignRight | Qt.AlignVCenter,
                       caption)
            p.setPen(QColor(color) if color else text_dim)
            for i, text in enumerate(texts):
                slot = self._slot(i)
                if text and fm.horizontalAdvance(text) + 2 <= slot.width():
                    p.drawText(QRectF(slot.left(), y, slot.width(), 16), Qt.AlignCenter, text)
        if self.reference is not None:
            value, label = self.reference
            y = round(plot.bottom() - plot.height() * (value / top_value))
            ink = QColor(self.c["text"])
            ink.setAlphaF(0.7)
            p.setPen(QPen(ink, 1, Qt.DashLine))
            p.drawLine(QPoint(plot.left(), y), QPoint(plot.right(), y))
            if label:           # sinon, libelle ailleurs (sous-titre de la carte)
                # libelle a droite, sur un cartouche du fond de la carte : lisible
                # meme pose sur les barres
                tw = fm.horizontalAdvance(label) + 8
                box = QRectF(plot.right() - tw, y - 9, tw, 18)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(self.c["panel"]))
                p.drawRoundedRect(box, 4, 4)
                p.setPen(ink)
                p.drawText(box, Qt.AlignCenter, label)
        if self.hover >= 0 and self.hasFocus():
            slot = self._slot(self.hover)
            p.setPen(QPen(QColor(self.c["text_dim"]), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(slot.adjusted(1, 1, -1, -1))
        p.end()

    def _visible_labels(self, fm) -> set:
        """Barres dont l'etiquette d'axe est dessinee : toutes si elles
        tiennent, sinon une sur n en partant de la plus recente - jamais de
        chevauchement, et un espacement regulier quelle que soit la largeur."""
        labelled = [i for i, bar in enumerate(self.bars) if bar[0]]
        if len(labelled) < 2:
            return set(labelled)
        spacing = self._slot(0).width() * (labelled[1] - labelled[0])
        widest = max(fm.horizontalAdvance(self.bars[i][0]) for i in labelled) + 10
        return set(labelled[::-1][::max(1, -(-int(widest) // max(1, int(spacing))))])

    # ----- survol et clavier : infobulle par barre -----
    def _index_at(self, x):
        plot = self._plot()
        if not self.bars or x < plot.left() or x > plot.right():
            return -1
        return min(len(self.bars) - 1, int((x - plot.left()) / (plot.width() / len(self.bars))))

    def _show_tip(self, i):
        self.hover = i
        self.update()
        if 0 <= i < len(self.bars):
            r = self._bar_rect(i)
            QToolTip.showText(self.mapToGlobal(QPoint(round(r.center().x()),
                                                      round(min(r.top(), self._plot().bottom() - 20)))),
                              self.bars[i][2], self)

    def mouseMoveEvent(self, event):
        i = self._index_at(event.position().x())
        if i != self.hover:
            self._show_tip(i)
            if i < 0:
                QToolTip.hideText()

    def leaveEvent(self, _event):
        self.hover = -1
        QToolTip.hideText()
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right) and self.bars:
            step = -1 if event.key() == Qt.Key_Left else 1
            start = self.hover if self.hover >= 0 else (len(self.bars) - 1 if step < 0 else 0) - step
            self._show_tip(max(0, min(len(self.bars) - 1, start + step)))
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self.hover = -1
        self.update()
        super().focusOutEvent(event)


class HBarList(QWidget):
    """Classement : sur une ligne le nom et sa valeur, dessous une barre fine
    (une teinte) proportionnelle. Sur deux lignes, il reste lisible quelle
    que soit la largeur de la carte. Seules les lignes qui tiennent dans la
    hauteur sont dessinees (les premieres du classement).

    `scale` : valeur d'une barre pleine largeur (1 pour des parts d'un tout :
    une part de 34 % fait 34 % de la piste, dessinee en clair) ; None : celle
    de la premiere ligne. Les lignes `clickable` (voir set_rows) reagissent
    au survol, au clic et au clavier (fleches, Entree) : signal activated."""

    activated = Signal(int)

    ROW = 38
    MIN_ROWS, MAX_ROWS = 3, 8
    PAD = 6      # marge du fond de survol autour d'une ligne

    def __init__(self, color, colors, empty_text="", scale=None):
        super().__init__()
        self.rows = []          # [(nom, valeur, texte de valeur)]
        self.clickable = set()
        self.color = QColor(color)
        self.c = colors
        self.empty_text = empty_text
        self.scale = scale
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(self.MIN_ROWS * self.ROW)

    def set_rows(self, rows, clickable=()):
        self.rows = list(rows)
        self.clickable = set(clickable)
        self.hover = -1
        self.setFocusPolicy(Qt.StrongFocus if self.clickable else Qt.NoFocus)
        self.update()

    def visible_rows(self) -> list:
        return self.rows[:max(1, self.height() // self.ROW)]

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = p.fontMetrics()
        pad = self.PAD if self.clickable else 0
        width = self.width() - 2 * pad
        if not self.rows:
            p.setPen(QColor(self.c["text_dim"]))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)
        peak = self.scale or max((r[1] for r in self.rows), default=0) or 1
        chevron = fm.horizontalAdvance("›") + 8 if self.clickable else 0
        track = QColor(self.color)
        track.setAlpha(55)
        for i, (name, value, text) in enumerate(self.visible_rows()):
            y = i * self.ROW
            if i == self.hover and i in self.clickable:
                p.setPen(QPen(QColor(self.c["text_dim"]), 1) if self.hasFocus() else Qt.NoPen)
                p.setBrush(QColor(self.c["button"]))
                p.drawRoundedRect(QRectF(0.5, y + 0.5, self.width() - 1, self.ROW - 3), 6, 6)
            x = pad
            right = x + width - chevron
            value_w = fm.horizontalAdvance(text)
            p.setPen(QColor(self.c["text_dim"]))
            p.drawText(QRect(right - value_w, y + 2, value_w, 20),
                       Qt.AlignVCenter | Qt.AlignRight, text)
            if i in self.clickable:
                p.drawText(QRect(right, y + 2, chevron, 20), Qt.AlignVCenter | Qt.AlignRight, "›")
            name_w = max(20, right - x - value_w - 12)
            p.setPen(QColor(self.c["text"]))
            p.drawText(QRect(x, y + 2, name_w, 20), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(name, Qt.ElideRight, name_w))
            bar_w = width - chevron
            p.setPen(Qt.NoPen)
            if self.scale:
                p.setBrush(track)
                p.drawRoundedRect(QRectF(x, y + 25, bar_w, 6), 3, 3)
            r = QRectF(x, y + 25, max(4.0, bar_w * min(1.0, value / peak)), 6)
            path = QPainterPath()
            path.setFillRule(Qt.WindingFill)   # formes superposees : union, pas de trous
            path.addRoundedRect(r, 3, 3)
            path.addRect(QRectF(r.left(), r.top(), 3, r.height()))   # base carree a gauche
            p.setBrush(self.color)
            p.drawPath(path.simplified())
        p.end()

    # ----- survol, clic et clavier -----
    def _row_at(self, y) -> int:
        i = int(y // self.ROW)
        return i if 0 <= i < len(self.visible_rows()) else -1

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.setCursor(Qt.PointingHandCursor if i in self.clickable else Qt.ArrowCursor)
            self.update()

    def mouseMoveEvent(self, event):
        self._set_hover(self._row_at(event.position().y()))

    def leaveEvent(self, _event):
        if not self.hasFocus():
            self._set_hover(-1)

    def mouseReleaseEvent(self, event):
        i = self._row_at(event.position().y())
        if event.button() == Qt.LeftButton and i in self.clickable:
            self.activated.emit(i)

    def keyPressEvent(self, event):
        rows = sorted(i for i in self.clickable if i < len(self.visible_rows()))
        if event.key() in (Qt.Key_Up, Qt.Key_Down) and rows:
            if self.hover in rows:
                pos = rows.index(self.hover) + (1 if event.key() == Qt.Key_Down else -1)
            else:
                pos = 0 if event.key() == Qt.Key_Down else len(rows) - 1
            self._set_hover(rows[max(0, min(len(rows) - 1, pos))])
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.hover in rows:
            self.activated.emit(self.hover)
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        if self.hover not in self.clickable and self.clickable:
            self._set_hover(min(self.clickable))
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._set_hover(-1)
        super().focusOutEvent(event)


class CalendarHeatmap(QWidget):
    """Calendrier de regularite : une case par jour, d'autant plus soutenue
    que le temps de lecture est long (une seule teinte, du clair au fonce ;
    case neutre sans lecture). Jusqu'a six semaines, un calendrier classique
    (une ligne par semaine, le quantieme dans la case) ; au-dela, une colonne
    par semaine. days : [stats.Bucket] par jour, dans l'ordre."""

    ALPHAS = (0.30, 0.50, 0.75, 1.0)    # nuances de la teinte, de « peu » a « beaucoup »
    GAP = 3
    HEADER, LEGEND = 18, 26
    DAY_MIN, DAY_MAX = 16, 34   # hauteur d'une case du calendrier mensuel
    WEEK_MAX = 16               # cote maximal d'une case de la vue par colonnes

    def __init__(self, color, colors):
        super().__init__()
        self.color = QColor(color)
        self.c = colors
        self.days = []
        self.weeks = []
        self.thresholds = []
        self.hover = -1
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        # six semaines de cases minimales, reperes et legende compris
        self.setMinimumHeight(self.HEADER + 6 * (self.DAY_MIN + self.GAP) + self.LEGEND)

    def set_days(self, days):
        self.days = list(days)
        self.weeks = stats.calendar_weeks(self.days)
        self.thresholds = stats.heat_thresholds(b.seconds for b in self.days)
        self.hover = -1
        self.update()

    def _grid_height(self) -> float:
        return self.height() - self.HEADER - self.LEGEND

    def _day_height(self) -> float:
        """Hauteur d'une case du calendrier mensuel, selon la place disponible."""
        return max(float(self.DAY_MIN), min(float(self.DAY_MAX),
                                            self._grid_height() / max(1, len(self.weeks)) - self.GAP))

    def _week_size(self) -> float:
        """Cote d'une case de la vue par colonnes, selon la place disponible."""
        return max(4.0, min(float(self.WEEK_MAX), self._grid_height() / 7 - 2,
                            (self.width() - 22) / max(1, len(self.weeks)) - 2))

    @property
    def monthly(self) -> bool:
        return len(self.weeks) <= 6

    def level(self, bucket) -> int:
        return stats.heat_level(bucket.seconds, self.thresholds)

    def _fill(self, level) -> QColor:
        if not level:
            return QColor(self.c["button"])
        color = QColor(self.color)
        color.setAlphaF(self.ALPHAS[min(level, len(self.ALPHAS)) - 1])
        return color

    def _ink(self, level) -> QColor:
        """Encre du quantieme : celle qui contraste le mieux avec la nuance
        de la case (la teinte, melangee au fond de la carte)."""
        if not level:
            return QColor(self.c["text_dim"])
        alpha = self.ALPHAS[min(level, len(self.ALPHAS)) - 1]
        base = QColor(self.c["panel"])
        fill = QColor(*(round(alpha * f + (1 - alpha) * b) for f, b in (
            (self.color.red(), base.red()), (self.color.green(), base.green()),
            (self.color.blue(), base.blue())))).name()
        return QColor(max((self.c["text"], theme.ON_ACCENT),
                          key=lambda ink: theme.contrast(ink, fill)))

    def _cells(self):
        """[(rectangle, index du jour)] des cases, selon la taille du widget."""
        cells, i = [], 0
        if self.monthly:
            ch = self._day_height()
            cw = (self.width() - 6 * self.GAP) / 7
            for row, week in enumerate(self.weeks):
                for col, bucket in enumerate(week):
                    if bucket is not None:
                        cells.append((QRectF(col * (cw + self.GAP),
                                             self.HEADER + row * (ch + self.GAP), cw, ch), i))
                        i += 1
        else:
            left, gap, size = 22, 2, self._week_size()
            for col, week in enumerate(self.weeks):
                for row, bucket in enumerate(week):
                    if bucket is not None:
                        cells.append((QRectF(left + col * (size + gap),
                                             self.HEADER + row * (size + gap), size, size), i))
                        i += 1
        return cells

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(_small_font(self))
        fm = p.fontMetrics()
        text, dim = QColor(self.c["text"]), QColor(self.c["text_dim"])
        cells = self._cells()
        monthly = self.monthly

        # reperes : jours de la semaine, et mois pour la vue par colonnes
        p.setPen(dim)
        if monthly:
            cw = (self.width() - 6 * self.GAP) / 7
            for col in range(7):
                p.drawText(QRectF(col * (cw + self.GAP), 0, cw, self.HEADER - 4),
                           Qt.AlignCenter, day_name(col))
        elif cells:
            size = cells[0][0].width()
            for row in ((0, 2, 4) if size >= 9 else ()):   # illisible sur des cases minuscules
                p.drawText(QRectF(0, self.HEADER + row * (size + 2), 18, size),
                           Qt.AlignVCenter | Qt.AlignLeft, day_name(row)[0].upper())
            last_right = -1.0
            for rect, i in cells:
                day = self.days[i].start
                label = month_name(day.month)
                x = min(rect.left(), self.width() - fm.horizontalAdvance(label))
                if day.day == 1 and x > last_right + 6:
                    p.drawText(QRectF(x, 0, 60, self.HEADER - 4),
                               Qt.AlignVCenter | Qt.AlignLeft, label)
                    last_right = x + fm.horizontalAdvance(label)

        radius = 4 if monthly else 2
        for rect, i in cells:
            level = self.level(self.days[i])
            p.setPen(Qt.NoPen)
            p.setBrush(self._fill(level))
            p.drawRoundedRect(rect, radius, radius)
            if monthly:
                # le quantieme, dans une encre lisible sur la nuance de la case
                p.setPen(self._ink(level))
                p.drawText(rect, Qt.AlignCenter, str(self.days[i].start.day))
        if 0 <= self.hover < len(cells):
            p.setPen(QPen(text, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(cells[self.hover][0].adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        # legende de l'echelle, a droite sous la grille
        box, x = 10, float(self.width())
        y = max((rect.bottom() for rect, _i in cells), default=float(self.HEADER)) + 10
        more = tr("Plus")
        x -= fm.horizontalAdvance(more)
        p.setPen(dim)
        p.drawText(QRectF(x, y - 3, 60, box + 6), Qt.AlignVCenter | Qt.AlignLeft, more)
        x -= 6
        for level in range(len(self.ALPHAS), -1, -1):
            x -= box
            p.setPen(Qt.NoPen)
            p.setBrush(self._fill(level))
            p.drawRoundedRect(QRectF(x, y, box, box), 2, 2)
            x -= 3
        less = tr("Moins")
        x -= 3 + fm.horizontalAdvance(less)
        p.setPen(dim)
        p.drawText(QRectF(x, y - 3, 60, box + 6), Qt.AlignVCenter | Qt.AlignLeft, less)
        p.end()

    # ----- survol et clavier : infobulle par jour -----
    def tip(self, i) -> str:
        b = self.days[i]
        date = f"{day_name(b.start.weekday())} {b.start.strftime(tr('%d/%m/%Y'))}"
        if not (b.seconds or b.pages):
            head, detail = tr("Pas de lecture"), date
        else:
            head = stats.fmt_duration(b.seconds)
            detail = f"{date} · " + trn(b.pages, "{n} page", "{n} pages")
        if b.finished:
            detail += " · " + trn(b.finished, "{n} tome terminé", "{n} tomes terminés")
        return f"{head}\n{detail}"

    def _show_tip(self, i):
        self.hover = i
        self.update()
        cells = self._cells()
        if 0 <= i < len(cells):
            rect = cells[i][0]
            QToolTip.showText(self.mapToGlobal(QPoint(round(rect.center().x()),
                                                      round(rect.top()))), self.tip(i), self)

    def mouseMoveEvent(self, event):
        pos = event.position()
        i = next((i for rect, i in self._cells()
                  if rect.adjusted(-2, -2, 2, 2).contains(pos)), -1)
        if i != self.hover:
            self._show_tip(i)
            if i < 0:
                QToolTip.hideText()

    def leaveEvent(self, _event):
        self.hover = -1
        QToolTip.hideText()
        self.update()

    def keyPressEvent(self, event):
        # un jour par fleche dans le sens des jours, une semaine dans l'autre
        day, week = ((Qt.Key_Left, Qt.Key_Right), (Qt.Key_Up, Qt.Key_Down))
        if not self.monthly:
            day, week = week, day
        steps = {day[0]: -1, day[1]: 1, week[0]: -7, week[1]: 7}
        if event.key() in steps and self.days:
            start = self.hover if self.hover >= 0 else len(self.days) - 1 - steps[event.key()]
            self._show_tip(max(0, min(len(self.days) - 1, start + steps[event.key()])))
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self.hover = -1
        self.update()
        super().focusOutEvent(event)


class FinishedList(QWidget):
    """Derniers tomes termines : une pastille (couleur « termine »), le titre
    et, a droite, la date. Des evenements rares se lisent mieux en liste
    qu'en graphique : on voit lesquels."""

    ROW = 30
    MIN_ROWS = 4

    def __init__(self, color, colors, empty_text=""):
        super().__init__()
        self.items = []     # [(titre, date, nombre de tomes de la ligne)]
        self.total = 0      # tomes termines sur la periode
        self.color = QColor(color)
        self.c = colors
        self.empty_text = empty_text
        self.setMinimumHeight(self.MIN_ROWS * self.ROW)

    def set_items(self, items, total):
        self.items = list(items)
        self.total = max(0, int(total))
        self.update()

    def visible_items(self) -> tuple:
        """(lignes dessinees, tomes termines non listes) : autant de lignes
        que la hauteur en contient, la derniere etant reservee au rappel
        « et n autres » quand tout ne tient pas."""
        capacity = max(1, self.height() // self.ROW)
        shown = self.items[:capacity]
        if self.total > sum(item[2] for item in shown):
            shown = self.items[:max(1, capacity - 1)]
        return shown, self.total - sum(item[2] for item in shown)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = p.fontMetrics()
        width = self.width()
        dim = QColor(self.c["text_dim"])
        if not self.items:
            p.setPen(dim)
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)
        shown, more = self.visible_items()
        for i, (title, date, _count) in enumerate(shown):
            y = i * self.ROW
            p.setPen(Qt.NoPen)
            p.setBrush(self.color)
            p.drawEllipse(QRectF(0, y + self.ROW / 2 - 4, 8, 8))
            date_w = fm.horizontalAdvance(date)
            p.setPen(dim)
            p.drawText(QRect(width - date_w, y, date_w, self.ROW),
                       Qt.AlignVCenter | Qt.AlignRight, date)
            title_w = max(20, width - date_w - 30)
            p.setPen(QColor(self.c["text"]))
            p.drawText(QRect(18, y, title_w, self.ROW), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(title, Qt.ElideRight, title_w))
        if self.items and more:
            p.setPen(dim)
            p.drawText(QRect(18, len(shown) * self.ROW, width - 18, self.ROW),
                       Qt.AlignVCenter | Qt.AlignLeft,
                       trn(more, "et {n} autre sur la période", "et {n} autres sur la période"))
        p.end()


class StackedBar(QWidget):
    """Barre de repartition (partie d'un tout) + legende sous la barre, qui
    passe a la ligne quand la carte est etroite."""

    LINE = 20

    def __init__(self, parts, colors):
        super().__init__()
        self.parts = parts        # [(libelle, nombre, couleur)]
        self.c = colors
        self.setMinimumHeight(26 + self.LINE)
        total = sum(n for _l, n, _c in parts)
        self.setToolTip("\n".join(
            tr("{label} : {value}", label=l, value=_fmt_int(n))
            + " (" + tr("{n} %", n=round(100 * n / total) if total else 0) + ")"
            for l, n, _c in parts))

    def _legend(self, fm) -> list:
        """[(x, y, texte, couleur)] des entrees de la legende, a la ligne
        quand la suivante ne tient plus dans la largeur."""
        out, lx, ly = [], 0, 28
        for label, n, color in self.parts:
            txt = f"{label}  {_fmt_int(n)}"
            item_w = 16 + fm.horizontalAdvance(txt)
            if lx and lx + item_w > self.width():
                lx, ly = 0, ly + self.LINE
            out.append((lx, ly, txt, color))
            lx += item_w + 22
        return out

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # la hauteur suit le nombre de lignes de la legende a cette largeur
        self.setMinimumHeight(self._legend(self.fontMetrics())[-1][1] + 18)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        total = sum(n for _l, n, _c in self.parts)
        width = self.width()
        x = 0.0
        visible = [(l, n, c) for l, n, c in self.parts if n > 0]
        gaps = 2 * (len(visible) - 1)
        for idx, (_label, n, color) in enumerate(visible):
            w = (width - gaps) * n / total
            r = QRectF(x, 0, w, 14)
            path = QPainterPath()
            path.setFillRule(Qt.WindingFill)   # formes superposees : union, pas de trous
            first, last = idx == 0, idx == len(visible) - 1
            path.addRoundedRect(r, 4, 4)
            if not first:
                path.addRect(QRectF(r.left(), 0, min(4, w), 14))
            if not last:
                path.addRect(QRectF(r.right() - min(4, w), 0, min(4, w), 14))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawPath(path.simplified())
            x += w + 2   # espace de 2 px couleur du fond entre les segments
        # legende : pastille + libelle + nombre (texte en couleur de texte)
        for lx, ly, txt, color in self._legend(p.fontMetrics()):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(lx, ly, 10, 10), 2, 2)
            p.setPen(QColor(self.c["text"]))
            p.drawText(QPoint(lx + 16, ly + 10), txt)
        p.end()


class ChartCard(QFrame):
    """Carte : titre, sous-titre et contenu. Avec `table_headers`, un bouton
    bascule le contenu vers le tableau de ses valeurs (voir set_table)."""

    def __init__(self, title, body, table_headers=None):
        super().__init__()
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(6)
        head = QHBoxLayout()
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("cardSub")
        self.subtitle.setWordWrap(True)
        self.subtitle.hide()
        self.stack = QStackedWidget()
        self.stack.addWidget(body)
        self.table = None
        if table_headers is not None:
            self.table = QTableWidget(0, len(table_headers))
            self.table.setHorizontalHeaderLabels(table_headers)
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.table.setMinimumHeight(body.minimumHeight())
            self.stack.addWidget(self.table)
            btn = QPushButton(tr("Tableau"))
            btn.setObjectName("toggle")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tr("Afficher les valeurs sous forme de tableau"))
            btn.toggled.connect(lambda on: (self.stack.setCurrentIndex(1 if on else 0),
                                            btn.setText(tr("Graphique") if on else tr("Tableau"))))
            head.addWidget(btn)
        v.addLayout(head)
        v.addWidget(self.subtitle)
        v.addWidget(self.stack)

    def set_title(self, text):
        self.title.setText(text)

    def set_subtitle(self, text):
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))

    def set_table(self, rows, headers=None):
        if headers is not None:
            self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for col, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                if col:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, col, item)



# ---------------------------------------------------------------- statistiques d'une serie

class Shelf(QWidget):
    """Etagere d'une serie : une case par tome (ou chapitre) dans l'ordre de
    lecture, son numero ecrit dedans, sa couleur selon son etat ; le tome en
    cours est rempli a proportion de sa progression, un tome non possede
    n'a qu'un contour pointille. Sous les cases, la legende avec les
    nombres : l'etat ne repose jamais sur la couleur seule.

    items : [(numero ecrit, etat, progression 0..1, infobulle)], etat parmi
    finished / reading / unread / missing. Au-dela de quatre rangees, les
    cases retrecissent et perdent leur numero (series en centaines de
    chapitres) ; le survol et le clavier le donnent toujours."""

    CELL_H, CELL_MIN, CELL_MAX, GAP = 30, 26, 44, 4
    SMALL, SMALL_MAX, SMALL_GAP = 10, 16, 2
    LEGEND = 26

    def __init__(self, colors_by_status, colors):
        super().__init__()
        self.fill = {k: QColor(v) for k, v in colors_by_status.items()}
        self.c = colors
        self.items = []
        self.legend = []    # [(texte, etat)]
        self.hover = -1
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(self.CELL_H + self.LEGEND)

    def set_items(self, items, legend):
        self.items = list(items)
        self.legend = list(legend)
        self.hover = -1
        self._fit()
        self.update()

    def _layout(self, width) -> tuple:
        """(colonnes, largeur et hauteur d'une case, espace, numeros ecrits)."""
        n = max(1, len(self.items))
        width = max(1, width)
        for small in (False, True):
            low, gap = (self.SMALL, self.SMALL_GAP) if small else (self.CELL_MIN, self.GAP)
            fit = max(1, int((width + gap) // (low + gap)))
            rows = -(-n // fit)
            if rows <= 4 or small:
                cols = -(-n // rows)    # rangees equilibrees
                cell = min(self.SMALL_MAX if small else self.CELL_MAX,
                           (width - (cols - 1) * gap) / cols)
                return cols, cell, (cell if small else self.CELL_H), gap, not small
        raise AssertionError

    def _cells(self) -> list:
        cols, cw, ch, gap, _numbers = self._layout(self.width())
        return [QRectF((i % cols) * (cw + gap), (i // cols) * (ch + gap), cw, ch)
                for i in range(len(self.items))]

    def _fit(self):
        cols, _cw, ch, gap, _n = self._layout(self.width())
        rows = -(-max(1, len(self.items)) // cols)
        self.setMinimumHeight(round(rows * (ch + gap)) + self.LEGEND)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    @staticmethod
    def _ink(color) -> QColor:
        return QColor(max(("#16181d", "#f5f0ee"), key=lambda ink: theme.contrast(ink, color.name())))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(_small_font(self))
        numbers = self._layout(self.width())[4]
        dim = QColor(self.c["text_dim"])
        cells = self._cells()
        radius = 4 if numbers else 2
        for i, ((label, status, progress, _tip), r) in enumerate(zip(self.items, cells, strict=True)):
            color = self.fill.get(status)
            ink = dim
            if status == "missing" or color is None:
                p.setPen(QPen(dim, 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
            elif status == "reading":
                soft = QColor(color)
                soft.setAlpha(60)
                p.setPen(QPen(color, 1))
                p.setBrush(soft)
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
                if progress > 0:
                    path = QPainterPath()
                    path.addRoundedRect(r, radius, radius)
                    p.save()
                    p.setClipRect(QRectF(r.left(), r.top(), r.width() * min(1.0, progress),
                                         r.height()))
                    p.setPen(Qt.NoPen)
                    p.setBrush(color)
                    p.drawPath(path)
                    p.restore()
                ink = QColor(self.c["text"])
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(r, radius, radius)
                ink = self._ink(color)
            if numbers and label:
                p.setPen(ink)
                p.drawText(r, Qt.AlignCenter, label)
            if i == self.hover:
                p.setPen(QPen(QColor(self.c["text"]), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), radius + 1, radius + 1)
        # legende : pastille + texte (couleur de texte)
        fm = p.fontMetrics()
        x, y = 0.0, max((r.bottom() for r in cells), default=0.0) + 10
        for text, status in self.legend:
            box = QRectF(x, y, 10, 10)
            if status in self.fill and status != "missing":
                p.setPen(Qt.NoPen)
                p.setBrush(self.fill[status])
            else:
                p.setPen(QPen(dim, 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box, 2, 2)
            p.setPen(dim)
            p.drawText(QPointF(x + 15, y + 9), text)
            x += 15 + fm.horizontalAdvance(text) + 18
        p.end()

    # ----- survol et clavier -----
    def _show_tip(self, i):
        self.hover = i
        self.update()
        cells = self._cells()
        if 0 <= i < len(cells):
            r = cells[i]
            QToolTip.showText(self.mapToGlobal(QPoint(round(r.center().x()), round(r.top()))),
                              self.items[i][3], self)

    def mouseMoveEvent(self, event):
        pos = event.position()
        i = next((i for i, r in enumerate(self._cells())
                  if r.adjusted(-2, -2, 2, 2).contains(pos)), -1)
        if i != self.hover:
            self._show_tip(i)
            if i < 0:
                QToolTip.hideText()

    def leaveEvent(self, _event):
        self.hover = -1
        QToolTip.hideText()
        self.update()

    def keyPressEvent(self, event):
        steps = {Qt.Key_Left: -1, Qt.Key_Right: 1}
        if event.key() in steps and self.items:
            step = steps[event.key()]
            start = self.hover if self.hover >= 0 else (len(self.items) if step < 0 else -1)
            self._show_tip(max(0, min(len(self.items) - 1, start + step)))
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self.hover = -1
        self.update()
        super().focusOutEvent(event)
