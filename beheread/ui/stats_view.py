"""Fenetre « Statistiques de lecture ».

Hierarchie de l'ecran, de haut en bas :

1. le choix de la periode (7 jours, 30 jours, 12 mois, tout), seul filtre,
   au-dessus de tout ce qu'il gouverne, et la legende de ce qui est compare ;
2. les chiffres cles : le temps de lecture en chiffre principal, puis pages,
   tomes termines et jours de lecture, chacun avec son ecart a la periode
   precedente et une mini-tendance ;
3. le detail : temps de lecture dans le temps et series les plus lues, puis
   regularite (calendrier) et derniers tomes termines ;
4. l'etat actuel de la bibliotheque, qui ne depend pas de la periode (sa
   carte le dit).

La fenetre s'ouvre en plein ecran et tout tient sur cet ecran, sans
defilement : les cartes s'etirent pour occuper la hauteur, leurs listes
n'affichent que les lignes qui y tiennent, et la seconde rangee est retiree
quand l'ecran n'est pas assez haut (voir StatsDialog.fit_height).

Les requetes sont dans reading_log.py, les calculs dans stats.py (purs,
testes) ; ce module ne fait que dessiner le rapport (stats.Report). Les
composants sont construits une fois puis mis a jour en place : changer de
periode ne deplace rien et ne perd pas la bascule « Tableau ».

Choix de visualisation :
* une forme par question : un chiffre pour un total, un histogramme pour une
  grandeur dans le temps, un calendrier pour la regularite, une jauge pour un
  ratio, un classement pour des series, une liste pour des evenements rares
  (les tomes termines) ;
* une seule teinte par graphique (couleur d'accent = activite de lecture,
  vert = tomes termines), la meme signification partout ; le calendrier
  decline l'accent du clair au fonce ;
* barres fines (<= 24 px) arrondies en haut, carrees a la base, separees par
  au moins 2 px ; grille en traits fins pleins et discrets ;
* une seule valeur ecrite directement (le maximum) : le survol (souris ou
  clavier) donne chaque valeur, et un tableau les liste toutes ;
* la repartition non lus / en cours / termines a une legende, les couleurs
  ont ete validees (daltonisme, contraste) sur les fonds clair et sombre.
"""

import datetime as dt
from pathlib import PureWindowsPath

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from beheread.core import stats
from beheread.core.reading_session import MIN_DWELL, PAUSE_CAP
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

MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
             "sept.", "oct.", "nov.", "déc."]
DAYS_FR = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def _fmt_int(n) -> str:
    return f"{int(n):,}".replace(",", " ")   # espace fine insecable


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
        lab = QLabel(label)
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

    def set_content(self, value, delta="", sub="", tip=""):
        self.value.setText(value)
        self.delta.setText(delta)
        self.delta.setVisible(bool(delta))
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        self.setToolTip(tip)
        self.setAccessibleName(" - ".join(
            t for t in (f"{self.label} : {value}", delta, sub) if t))


class BarChart(QWidget):
    """Histogramme vertical a une serie. bars : [(etiquette d'axe ou "",
    valeur, texte d'infobulle)]."""

    BAR_MAX = 24
    GAP = 2
    LEFT, RIGHT, TOP, BOTTOM = 52, 8, 22, 26

    def __init__(self, color, colors, value_fmt=_fmt_int, empty_text="",
                 ticks=stats.nice_ticks, height=150):
        """`ticks` : fonction (maximum) -> graduations de l'axe des valeurs."""
        super().__init__()
        self.bars = []
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

    def set_bars(self, bars):
        self.bars = list(bars)
        self.ticks = self.tick_fn(max((b[1] for b in self.bars), default=0))
        self.hover = -1
        self.update()

    def sizeHint(self):
        return QSize(420, self.minimumHeight() + 10)

    def _plot(self):
        return QRect(self.LEFT, self.TOP, self.width() - self.LEFT - self.RIGHT,
                     self.height() - self.TOP - self.BOTTOM)

    def _slot(self, i):
        plot = self._plot()
        w = plot.width() / max(1, len(self.bars))
        return QRectF(plot.left() + i * w, plot.top(), w, plot.height())

    def _bar_rect(self, i):
        plot = self._plot()
        slot = self._slot(i)
        bw = max(2.0, min(self.BAR_MAX, slot.width() - self.GAP))
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
                if i == peak_i:
                    p.setPen(QColor(self.c["text"]))
                    txt = self.value_fmt(value)
                    tw = fm.horizontalAdvance(txt)
                    x = max(plot.left(), min(plot.right() - tw - 4, r.center().x() - tw / 2 - 2))
                    p.drawText(QRectF(x, r.top() - 18, tw + 4, 16), Qt.AlignCenter, txt)
            if i in shown:
                slot = self._slot(i)
                tw = fm.horizontalAdvance(label)
                p.setPen(text_dim)
                p.drawText(QRectF(slot.center().x() - tw / 2 - 2, plot.bottom() + 6, tw + 4, 16),
                           Qt.AlignCenter, label)
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
    hauteur sont dessinees (les premieres du classement)."""

    ROW = 38
    MIN_ROWS, MAX_ROWS = 3, 8

    def __init__(self, color, colors, empty_text=""):
        super().__init__()
        self.rows = []          # [(nom, valeur, texte de valeur)]
        self.color = QColor(color)
        self.c = colors
        self.empty_text = empty_text
        self.setMinimumHeight(self.MIN_ROWS * self.ROW)

    def set_rows(self, rows):
        self.rows = list(rows)
        self.update()

    def visible_rows(self) -> list:
        return self.rows[:max(1, self.height() // self.ROW)]

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = p.fontMetrics()
        width = self.width()
        if not self.rows:
            p.setPen(QColor(self.c["text_dim"]))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)
        peak = max((r[1] for r in self.rows), default=0) or 1
        for i, (name, value, text) in enumerate(self.visible_rows()):
            y = i * self.ROW
            value_w = fm.horizontalAdvance(text)
            p.setPen(QColor(self.c["text_dim"]))
            p.drawText(QRect(width - value_w, y, value_w, 20), Qt.AlignVCenter | Qt.AlignRight, text)
            name_w = max(20, width - value_w - 12)
            p.setPen(QColor(self.c["text"]))
            p.drawText(QRect(0, y, name_w, 20), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(name, Qt.ElideRight, name_w))
            r = QRectF(0, y + 24, max(4.0, width * value / peak), 6)
            path = QPainterPath()
            path.setFillRule(Qt.WindingFill)   # formes superposees : union, pas de trous
            path.addRoundedRect(r, 3, 3)
            path.addRect(QRectF(r.left(), r.top(), 3, r.height()))   # base carree a gauche
            p.setPen(Qt.NoPen)
            p.setBrush(self.color)
            p.drawPath(path.simplified())
        p.end()


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
            for col, name in enumerate(DAYS_FR):
                p.drawText(QRectF(col * (cw + self.GAP), 0, cw, self.HEADER - 4),
                           Qt.AlignCenter, name)
        elif cells:
            size = cells[0][0].width()
            for row in ((0, 2, 4) if size >= 9 else ()):   # illisible sur des cases minuscules
                p.drawText(QRectF(0, self.HEADER + row * (size + 2), 18, size),
                           Qt.AlignVCenter | Qt.AlignLeft, DAYS_FR[row][0].upper())
            last_right = -1.0
            for rect, i in cells:
                day = self.days[i].start
                label = MONTHS_FR[day.month - 1]
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
        more = "Plus"
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
        less = "Moins"
        x -= 3 + fm.horizontalAdvance(less)
        p.setPen(dim)
        p.drawText(QRectF(x, y - 3, 60, box + 6), Qt.AlignVCenter | Qt.AlignLeft, less)
        p.end()

    # ----- survol et clavier : infobulle par jour -----
    def tip(self, i) -> str:
        b = self.days[i]
        date = f"{DAYS_FR[b.start.weekday()]} {b.start.strftime('%d/%m/%Y')}"
        if not (b.seconds or b.pages):
            head, detail = "Pas de lecture", date
        else:
            head, detail = stats.fmt_duration(b.seconds), f"{date} · {_plural(b.pages, 'page')}"
        if b.finished:
            detail += f" · {_plural(b.finished, 'tome terminé', 'tomes terminés')}"
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
                       f"et {_plural(more, 'autre')} sur la période")
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
        self.setToolTip("\n".join(f"{l} : {_fmt_int(n)} ({round(100 * n / total) if total else 0} %)"
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
            btn = QPushButton("Tableau")
            btn.setObjectName("toggle")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("Afficher les valeurs sous forme de tableau")
            btn.toggled.connect(lambda on: (self.stack.setCurrentIndex(1 if on else 0),
                                            btn.setText("Graphique" if on else "Tableau")))
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


# ---------------------------------------------------------------- mise en forme du rapport

def _plural(n, singular, plural=None) -> str:
    return f"{_fmt_int(n)} {singular if n < 2 else (plural or singular + 's')}"


def _fmt_day(d, year=True) -> str:
    day = "1er" if d.day == 1 else str(d.day)
    return f"{day} {MONTHS_FR[d.month - 1]}" + (f" {d.year}" if year else "")


def _fmt_range(start, end) -> str:
    if start == end:
        return _fmt_day(end)
    return f"{_fmt_day(start, year=start.year != end.year)} – {_fmt_day(end)}"


def _comparable(report, since) -> bool:
    """La periode precedente est-elle couverte par la mesure (`since` : son
    premier jour) ? Sinon, on ne compare pas plutot que d'afficher une
    hausse trompeuse."""
    previous = report.period.previous
    return previous is not None and since is not None and since <= previous[1]


def _delta(current, previous, short, full, report, since) -> tuple:
    """Ecart avec la periode precedente : (texte court de la tuile, phrase
    complete de son infobulle). `short` et `full` mettent l'ecart en forme."""
    period = report.period
    if previous is None or period.previous is None:
        return "", ""
    if not _comparable(report, since):
        return "", (f"Mesuré depuis le {since.strftime('%d/%m/%Y')} : rien à comparer "
                    f"sur les {period.previous_label}." if since else "")
    diff = current - previous
    if not diff:
        return "= identique", f"Autant que les {period.previous_label} ({full(previous)})."
    arrow, word = ("▲", "plus") if diff > 0 else ("▼", "moins")
    return (f"{arrow} {short(abs(diff))}",
            f"{full(abs(diff))} de {word} que les {period.previous_label} ({full(previous)}).")


def _caption(report) -> str:
    """Sous le titre : les dates de la periode et ce a quoi elle est
    comparee, dit une fois pour toutes les tuiles."""
    period = report.period
    span = _fmt_range(period.start, period.end)
    if period.previous is None or report.first_day is None:
        return span
    if not _comparable(report, report.first_day):
        return f"{span} · historique trop court pour comparer"
    return f"{span} · comparé aux {period.previous_label}"


def _bucket_name(bucket, grain, short=False) -> str:
    d = bucket.start
    if grain == "month":
        return f"{MONTHS_FR[d.month - 1]} {d.year}"
    return d.strftime("%d/%m" if short else "%d/%m/%Y")


def _axis_labels(buckets, grain) -> list:
    """Etiquettes de l'axe du temps : toutes s'il y a peu de barres, sinon
    une sur n en partant de la plus recente (qui est toujours etiquetee)."""
    n = len(buckets)
    limit = 12 if grain == "month" else 7
    step = max(1, -(-n // limit))
    labels = []
    for i, b in enumerate(buckets):
        if (n - 1 - i) % step:
            labels.append("")
        elif grain == "month":
            year = f" {b.start.year % 100:02d}" if b.start.month == 1 else ""
            labels.append(MONTHS_FR[b.start.month - 1] + year)
        else:
            labels.append(f"{b.start.day}/{b.start.month}")
    return labels


def _fmt_pace(seconds) -> str:
    text = f"{seconds:.0f}" if seconds >= 10 else f"{seconds:.1f}".replace(".", ",")
    return f"{text} s par page"


# ---------------------------------------------------------------- fenetre

class StatsDialog(QDialog):
    def __init__(self, store, library, mode, parent=None, today=None, resolve=None,
                 titles=None):
        """library : etat de la bibliotheque - {"unread": n, "reading": n,
        "finished": n} et, pour le temps restant a lire, "remaining_pages"
        (pages non lues des tomes non termines) et "unknown_pages" (tomes
        dont le nombre de pages est inconnu).
        resolve : empreinte d'un tome -> (cle de serie, nom affiche) selon la
        bibliotheque actuelle, ou None (voir stats.top_series).
        titles : {empreinte: titre actuel du tome} (liste des tomes termines)."""
        super().__init__(parent)
        self.setWindowTitle("Statistiques de lecture")
        self.store = store
        self.library = library
        self.resolve = resolve
        self.titles = titles or {}
        self.today = today or dt.date.today()
        self.c = c = theme.colors(mode)
        self.dc = data_colors(mode)
        self.report = None

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 18, 22, 18)
        self.root.setSpacing(14)
        # la fenetre a la taille de l'ecran : c'est le contenu qui s'y adapte
        # (voir fit_height), jamais la fenetre qui grandit avec son contenu
        self.root.setSizeConstraint(QLayout.SetNoConstraint)
        self.root.addLayout(self._build_header())
        self._build_body()

        self.setStyleSheet(f"""
            QDialog {{ background: {c['window']}; }}
            QLabel {{ color: {c['text']}; }}
            QToolTip {{
                color: {c['text']}; background: {c['panel']};
                border: 1px solid {c['border']}; padding: 4px 6px;
            }}
            #statsTitle {{ font-size: 20px; font-weight: 700; }}
            #tile, #card {{
                background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px;
            }}
            #tileLabel {{ color: {c['text_dim']}; font-size: 12px; }}
            #tileValue {{ font-size: 24px; font-weight: 600; }}
            #heroValue {{ font-size: 44px; font-weight: 600; }}
            #tileDelta {{ font-size: 13px; }}
            #tileSub, #cardSub, #caption {{ color: {c['text_dim']}; font-size: 12px; }}
            #cardTitle {{ font-size: 14px; font-weight: 700; }}
            #backlogValue {{ font-size: 24px; font-weight: 600; }}
            #emptyTitle {{ font-size: 15px; font-weight: 600; }}
            QPushButton {{
                color: {c['text']}; background: {c['button']};
                border: 1px solid {c['border']}; border-radius: 8px; padding: 5px 14px;
            }}
            QPushButton:hover {{ background: {c['button_hover']}; }}
            QPushButton:focus {{ border: 2px solid {theme.ACCENT}; }}
            QPushButton#toggle {{ padding: 2px 10px; font-size: 12px; }}
            QPushButton#link {{
                background: transparent; border: none; padding: 2px 0;
                color: {c['text_dim']}; font-size: 12px; text-decoration: underline;
            }}
            QPushButton#link:hover {{ color: {c['text']}; }}
            QPushButton#seg {{
                padding: 5px 14px; font-size: 12px; border-radius: 0; margin-left: -1px;
            }}
            QPushButton#seg[pos="first"] {{
                margin-left: 0; border-top-left-radius: 8px; border-bottom-left-radius: 8px;
            }}
            QPushButton#seg[pos="last"] {{
                border-top-right-radius: 8px; border-bottom-right-radius: 8px;
            }}
            QPushButton#seg:checked {{
                background: {theme.ACCENT_SOFT}; border: 1px solid {theme.ACCENT};
            }}
            QTableWidget {{
                color: {c['text']}; background: {c['panel']};
                gridline-color: {c['border']}; border: none;
            }}
            QHeaderView::section {{
                color: {c['text_dim']}; background: {c['panel']};
                border: none; border-bottom: 1px solid {c['border']}; padding: 4px;
            }}
        """)
        # plein ecran, sur l'ecran de la bibliotheque
        screen = parent.screen() if parent is not None else QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.setWindowState(self.windowState() | Qt.WindowFullScreen)
        self.set_period(store.ui_pref("stats_period", stats.DEFAULT_PERIOD))

    # ------------------------------------------------------------ construction
    def _build_header(self):
        """En-tete : titre, choix de la periode (qui gouverne tout ce qui
        suit), fermeture ; dessous, les dates de la periode et l'acces a la
        methode de mesure."""
        v = QVBoxLayout()
        v.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("Statistiques de lecture")
        title.setObjectName("statsTitle")
        head.addWidget(title)
        head.addStretch(1)

        segmented = QWidget()
        seg = QHBoxLayout(segmented)
        seg.setContentsMargins(0, 0, 0, 0)
        seg.setSpacing(0)
        self.period_buttons = {}
        group = QButtonGroup(self)
        for i, (key, label) in enumerate(stats.PERIODS):
            btn = QPushButton(label)
            btn.setObjectName("seg")
            btn.setProperty("pos", "first" if i == 0 else
                            ("last" if i == len(stats.PERIODS) - 1 else "mid"))
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.toggled.connect(lambda on, k=key: on and self._choose_period(k))
            group.addButton(btn)
            seg.addWidget(btn)
            self.period_buttons[key] = btn
        head.addWidget(segmented)
        # en plein ecran, il n'y a pas de barre de titre : la fermeture est ici
        self.close_button = QPushButton("Fermer")
        self.close_button.setToolTip("Fermer les statistiques (Échap)")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.clicked.connect(self.accept)
        head.addWidget(self.close_button)
        v.addLayout(head)

        row = QHBoxLayout()
        self.caption = QLabel()
        self.caption.setObjectName("caption")
        row.addWidget(self.caption, 1)
        # la methode s'affiche en infobulle (survol ou clic) : elle ne prend
        # aucune place a l'ecran
        self.method = QPushButton("Méthode de mesure")
        self.method.setObjectName("link")
        self.method.setCursor(Qt.PointingHandCursor)
        self.method.setToolTip(
            f"<qt>Une page compte comme lue après {MIN_DWELL:.0f} s d'affichage (feuilleter ne "
            f"compte pas) ; le temps de lecture ignore les pauses de plus de {PAUSE_CAP:.0f} s. "
            "Un tome est terminé quand sa dernière page est atteinte dans le lecteur : "
            "« Marquer comme lu » ne compte pas comme une lecture.</qt>")
        self.method.clicked.connect(lambda: QToolTip.showText(
            self.method.mapToGlobal(QPoint(0, self.method.height())),
            self.method.toolTip(), self.method))
        row.addWidget(self.method)
        v.addLayout(row)
        return v

    def _build_body(self):
        c, dc = self.c, self.dc

        # --- etat vide : un seul message, a la place des chiffres et graphiques
        self.empty_card = QFrame()
        self.empty_card.setObjectName("card")
        ev = QVBoxLayout(self.empty_card)
        ev.setContentsMargins(24, 28, 24, 28)
        ev.setSpacing(6)
        empty_title = QLabel("Aucune lecture enregistrée pour l'instant")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_text = QLabel("Ouvrez un tome : le temps de lecture, les pages lues et les tomes "
                            "terminés apparaîtront ici au fil de vos lectures.")
        empty_text.setObjectName("cardSub")
        empty_text.setAlignment(Qt.AlignCenter)
        empty_text.setWordWrap(True)
        ev.addStretch(1)
        ev.addWidget(empty_title)
        ev.addWidget(empty_text)
        ev.addStretch(1)
        self.root.addWidget(self.empty_card, 1)

        # --- chiffres cles
        self.pages_spark = Sparkline(dc["activity"], c)
        self.finished_spark = Sparkline(dc["finished"], c)
        self.days_meter = Meter(dc["activity"])
        self.tiles = [StatTile("Temps de lecture", hero=True),
                      StatTile("Pages lues", self.pages_spark),
                      StatTile("Tomes terminés", self.finished_spark),
                      StatTile("Jours de lecture", self.days_meter)]
        self.tiles_host = QWidget()
        grid = QGridLayout(self.tiles_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.addWidget(self.tiles[0], 0, 0, 1, 2)    # chiffre principal : double largeur
        for i, tile in enumerate(self.tiles[1:]):
            grid.addWidget(tile, 0, 2 + i)
        for col in range(5):
            grid.setColumnStretch(col, 1)
        self.root.addWidget(self.tiles_host)

        # --- premiere rangee : le temps de lecture et les series
        self.time_chart = BarChart(dc["activity"], c, ticks=stats.time_ticks,
                                   value_fmt=lambda s: stats.fmt_duration(s, compact=True),
                                   empty_text="Aucune lecture enregistrée sur la période.")
        self.time_card = ChartCard("Temps de lecture", self.time_chart,
                                   ["Jour", "Temps", "Pages", "Tomes terminés"])
        self.series_list = HBarList(dc["activity"], c, "Aucune lecture enregistrée sur la période.")
        self.series_card = ChartCard("Séries les plus lues", self.series_list)
        self.series_card.set_subtitle("Part du temps de lecture")
        self.detail = QWidget()
        row = QHBoxLayout(self.detail)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(self.time_card, 3)
        row.addWidget(self.series_card, 1)
        self.root.addWidget(self.detail, 1)

        # --- seconde rangee : regularite, tomes termines, bibliotheque. C'est
        # elle qui est retiree quand l'ecran n'est pas assez haut (fit_height).
        self.calendar = CalendarHeatmap(dc["activity"], c)
        self.calendar_card = ChartCard("Régularité", self.calendar)
        self.finished_list = FinishedList(dc["finished"], c, "Aucun tome terminé sur la période.")
        self.finished_card = ChartCard("Tomes terminés", self.finished_list)
        self.library_card = self._library_card()
        self.habits = QWidget()
        row = QHBoxLayout(self.habits)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(self.calendar_card, 2)
        row.addWidget(self.finished_card, 1)
        row.addWidget(self.library_card, 1)
        self.root.addWidget(self.habits, 1)

    def _library_card(self):
        """Etat actuel de la bibliotheque : il ne depend pas de la periode,
        et la carte le dit."""
        lib = self.library
        parts = [("Terminés", lib.get("finished", 0), self.dc["finished"]),
                 ("En cours", lib.get("reading", 0), self.dc["reading"]),
                 ("Non lus", lib.get("unread", 0), self.dc["unread"])]
        total = sum(n for _l, n, _c in parts)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        if total:
            v.addWidget(StackedBar(parts, self.c))
            v.addSpacing(8)
        label = QLabel("Reste à lire")
        label.setObjectName("tileLabel")
        value, detail = self._backlog()
        self.backlog_value = QLabel(value)
        self.backlog_value.setObjectName("backlogValue")
        self.backlog_value.setVisible(bool(value))
        self.backlog_detail = QLabel(detail)
        self.backlog_detail.setObjectName("cardSub")
        self.backlog_detail.setWordWrap(True)
        v.addWidget(label)
        v.addWidget(self.backlog_value)
        v.addWidget(self.backlog_detail)
        v.addStretch(1)
        card = ChartCard("Bibliothèque", body)
        card.set_subtitle((f"{_plural(total, 'tome')} · " if total else "Vide · ")
                          + "indépendant de la période")
        return card

    def _backlog(self) -> tuple:
        """(chiffre, precision) du temps qu'il reste a lire dans la
        bibliotheque, au rythme habituel."""
        pace = self.store.median_page_seconds()
        remaining = self.library.get("remaining_pages", 0)
        if not pace:
            return "", ("Rythme de lecture pas encore mesuré : l'estimation s'affichera "
                        "après quelques pages lues.")
        if not remaining:
            return "", f"Rien en attente. Votre rythme : {_fmt_pace(pace)}."
        seconds = remaining * pace
        # au-dela de dix heures, les minutes d'une estimation n'ont pas de sens
        duration = (f"{_fmt_int(round(seconds / 3600))} h" if seconds >= 36000
                    else stats.fmt_duration(seconds, compact=True))
        detail = f"{_plural(remaining, 'page')} à votre rythme de {_fmt_pace(pace)}"
        unknown = self.library.get("unknown_pages", 0)
        if unknown:
            detail += f", hors {_plural(unknown, 'tome')} au nombre de pages inconnu"
        return f"≈ {duration}", detail + "."

    # ------------------------------------------------------------ un seul ecran
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_height()

    def showEvent(self, event):
        super().showEvent(event)
        # une fois les cartes a leur largeur reelle (la hauteur de certaines
        # en depend), on verifie de nouveau que tout tient
        QTimer.singleShot(0, self.fit_height)

    def fit_height(self):
        """Tout tient sur un ecran, sans defilement. Les cartes s'etirent pour
        occuper la hauteur disponible, et leurs listes n'affichent que les
        lignes qui y tiennent ; quand meme leur hauteur minimale ne tient pas,
        la seconde rangee (regularite, tomes termines, bibliotheque) est
        retiree et la premiere garde toute la place."""
        if self.report is None or self.report.first_day is None:
            self.habits.setVisible(True)    # journal vide : le message et la bibliotheque
            return
        self.root.activate()
        needed = self.root.minimumSize().height()
        if self.habits.isHidden():
            needed += self.root.spacing() + self.habits.minimumSizeHint().height()
        self.habits.setVisible(needed <= self.height())

    # ------------------------------------------------------------ periode
    def _choose_period(self, key):
        if self.report is not None and self.report.period.key == key:
            return
        self.set_period(key)
        self.store.set_ui_pref("stats_period", self.report.period.key)

    def set_period(self, key):
        """Recalcule le rapport pour la periode et met a jour chaque
        composant en place."""
        self.report = stats.build_report(self.store.reading_log, key, self.today, self.resolve,
                                         top=HBarList.MAX_ROWS)
        self.period_buttons[self.report.period.key].setChecked(True)
        self._refresh(self.report)

    # ------------------------------------------------------------ mise a jour
    def _refresh(self, report):
        empty = report.first_day is None
        self.empty_card.setVisible(empty)
        for block in (self.tiles_host, self.detail, self.calendar_card, self.finished_card):
            block.setVisible(not empty)
        self.caption.setText(_caption(report))
        self._refresh_tiles(report)
        self._refresh_time(report)
        self._refresh_series(report)
        self._refresh_calendar(report)
        self._refresh_finished(report)
        self.fit_height()

    def _refresh_tiles(self, report):
        t, prev, period = report.totals, report.previous, report.period
        measured = report.first_session   # pages et temps ne sont mesures que depuis ce jour
        hero, pages, finished, days = self.tiles

        details = []
        if t.active_days and t.seconds:
            details.append(f"{stats.fmt_duration(t.seconds / t.active_days)} par jour de lecture")
        if t.sessions:
            details.append(_plural(t.sessions, "séance"))
        # compare a la minute pres : un ecart de quelques secondes n'en est pas un
        delta, tip = _delta(round(t.seconds / 60) * 60, prev and round(prev.seconds / 60) * 60,
                            stats.fmt_duration, stats.fmt_duration, report, measured)
        hero.set_content(stats.fmt_duration(t.seconds), delta, " · ".join(details), tip)

        delta, tip = _delta(t.pages, prev and prev.pages, _fmt_int,
                            lambda n: _plural(n, "page"), report, measured)
        pages.set_content(_fmt_int(t.pages), delta,
                          f"dans {_plural(t.volumes, 'tome')}" if t.volumes else "", tip)
        self.pages_spark.set_values(b.pages for b in report.buckets)

        delta, tip = _delta(t.finished, prev and prev.finished, _fmt_int,
                            lambda n: _plural(n, "tome"), report, report.first_day)
        finished.set_content(_fmt_int(t.finished), delta, "", tip)
        self.finished_spark.set_values(b.finished for b in report.buckets)

        delta, tip = _delta(t.active_days, prev and prev.active_days, _fmt_int,
                            lambda n: _plural(n, "jour"), report, measured)
        days.set_content(f"{_fmt_int(t.active_days)} sur {_fmt_int(period.days)}", delta, "", tip)
        self.days_meter.set_ratio(t.active_days / period.days)

    def _refresh_time(self, report):
        grain = report.period.grain
        bars, rows = [], []
        for label, b in zip(_axis_labels(report.buckets, grain), report.buckets):
            # la valeur d'abord, puis ce qui la situe
            detail = f"{_bucket_name(b, grain, short=True)} · {_plural(b.pages, 'page')}"
            if b.finished:
                detail += f" · {_plural(b.finished, 'tome terminé', 'tomes terminés')}"
            bars.append((label, b.seconds, f"{stats.fmt_duration(b.seconds)}\n{detail}"))
            rows.append((_bucket_name(b, grain), stats.fmt_duration(b.seconds),
                         _fmt_int(b.pages), _fmt_int(b.finished)))
        unit = "mois" if grain == "month" else "jour"
        self.time_chart.set_bars(bars)
        self.time_card.set_title(f"Temps de lecture par {unit}")
        self.time_card.set_table(list(reversed(rows)),
                                 [unit.capitalize(), "Temps", "Pages", "Tomes terminés"])

    def _refresh_series(self, report):
        timed = any(s.seconds for s in report.series)
        self.series_list.set_rows(
            (s.name, s.seconds if timed else s.pages,
             f"{stats.fmt_duration(s.seconds, compact=True) if timed else _plural(s.pages, 'page')}"
             f" · {round(100 * s.share)} %")
            for s in report.series)

    def _refresh_calendar(self, report):
        self.calendar.set_days(report.calendar)
        streak = (f"Série en cours : {_plural(report.streak, 'jour')}" if report.streak
                  else "Pas de série en cours")
        if report.best_streak > report.streak:
            streak += f" · record : {_plural(report.best_streak, 'jour')}"
        if report.calendar and report.calendar[0].start > report.period.start:
            streak += " · 53 dernières semaines affichées"
        self.calendar_card.set_subtitle(streak)

    def _refresh_finished(self, report):
        items, unknown = [], {}   # unknown : jour -> position de sa ligne « tomes absents »
        for day, volume, title, series in report.finished_volumes:
            date = _fmt_day(day, year=day.year != self.today.year)
            name = self.titles.get(volume) or title or series
            if not name and not volume.startswith("c1:"):
                # ancienne entree indexee par chemin, peut-etre venue d'un autre
                # systeme (sauvegarde importee) : PureWindowsPath coupe sur \ et /
                name = PureWindowsPath(volume).stem
            if name:
                items.append((name, date, 1))
                continue
            # fichier supprime depuis, termine avant le journal : son titre est
            # perdu. Une seule ligne par jour plutot qu'une ligne identique par tome.
            if day not in unknown:
                unknown[day] = len(items)
                items.append(("", date, 0))
            count = items[unknown[day]][2] + 1
            items[unknown[day]] = (_plural(count, "tome absent de la bibliothèque",
                                           "tomes absents de la bibliothèque"), date, count)
        total = report.totals.finished
        self.finished_list.set_items(items, total)
        self.finished_card.set_subtitle(
            f"{_plural(total, 'tome lu', 'tomes lus')} jusqu'à la dernière page" if total else "")
