"""Fenetre « Statistiques de lecture » : chiffres cles, activite des 30
derniers jours, tomes termines par mois, series les plus lues et repartition
de la bibliotheque. Les calculs sont dans stats.py (purs, testes) ; ce module
ne fait que dessiner.

Choix de visualisation :
* une seule teinte par graphique a une seule serie (rouge d'accent = activite
  de lecture, vert = tomes termines), la meme signification partout ;
* barres fines (<= 24 px) arrondies en haut, carrees a la base, separees par
  au moins 2 px ; grille en traits fins pleins et discrets ;
* une seule valeur ecrite directement (le maximum) : le survol (souris ou
  clavier) donne chaque valeur, et un tableau les liste toutes ;
* la repartition non lus / en cours / termines a une legende, les couleurs
  ont ete validees (daltonisme, contraste) sur les fonds clair et sombre.
"""

import datetime as dt

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from beheread.core import stats
from beheread.ui import theme

# couleurs de donnees (validees avec le script de la methode dataviz)
DATA_COLORS = {
    "dark": {"activity": theme.ACCENT, "finished": "#3fa35f", "unread": "#3987e5",
             "reading": theme.ACCENT},
    "light": {"activity": theme.ACCENT, "finished": "#3fa35f", "unread": "#2a78d6",
              "reading": theme.ACCENT},
}

MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
             "sept.", "oct.", "nov.", "déc."]


def _fmt_int(n) -> str:
    return f"{int(n):,}".replace(",", " ")   # espace fine insecable


# ---------------------------------------------------------------- briques

class StatTile(QFrame):
    def __init__(self, label, value, sub=""):
        super().__init__()
        self.setObjectName("tile")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(2)
        lab = QLabel(label)
        lab.setObjectName("tileLabel")
        val = QLabel(value)
        val.setObjectName("tileValue")
        v.addWidget(lab)
        v.addWidget(val)
        if sub:
            s = QLabel(sub)
            s.setObjectName("tileSub")
            s.setWordWrap(True)
            v.addWidget(s)
        v.addStretch(1)
        self.setAccessibleName(f"{label} : {value}" + (f" ({sub})" if sub else ""))


class BarChart(QWidget):
    """Histogramme vertical a une serie. bars : [(etiquette d'axe ou "",
    valeur, texte d'infobulle)]."""

    BAR_MAX = 24
    GAP = 2
    LEFT, RIGHT, TOP, BOTTOM = 44, 8, 22, 26

    def __init__(self, bars, color, colors, value_fmt=_fmt_int, empty_text=""):
        super().__init__()
        self.bars = bars
        self.color = QColor(color)
        self.c = colors
        self.value_fmt = value_fmt
        self.empty_text = empty_text
        self.hover = -1
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(190)
        peak = max((b[1] for b in bars), default=0)
        self.ticks = stats.nice_ticks(peak)

    def sizeHint(self):
        return QSize(560, 200)

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
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() * 0.85))
        p.setFont(small)
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
                if i == peak_i and value > 0:
                    p.setPen(QColor(self.c["text"]))
                    txt = self.value_fmt(value)
                    tw = fm.horizontalAdvance(txt)
                    p.drawText(QRectF(r.center().x() - tw / 2 - 2, r.top() - 18, tw + 4, 16),
                               Qt.AlignCenter, txt)
            if label:
                slot = self._slot(i)
                p.setPen(text_dim)
                tw = fm.horizontalAdvance(label)
                p.drawText(QRectF(slot.center().x() - tw / 2 - 2, plot.bottom() + 6, tw + 4, 16),
                           Qt.AlignCenter, label)
        if self.hover >= 0 and self.hasFocus():
            slot = self._slot(self.hover)
            p.setPen(QPen(QColor(self.c["text_dim"]), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(slot.adjusted(1, 1, -1, -1))
        p.end()

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
    """Classement horizontal : nom, barre (une teinte), valeur en fin de barre."""

    ROW = 26

    def __init__(self, rows, color, colors):
        super().__init__()
        self.rows = rows          # [(nom, valeur, texte de valeur)]
        self.color = QColor(color)
        self.c = colors
        self.setMinimumHeight(max(1, len(rows)) * self.ROW + 4)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = p.fontMetrics()
        name_w = min(220, int(self.width() * 0.38))
        value_w = 90
        bar_left = name_w + 12
        bar_max = max(10, self.width() - bar_left - value_w - 8)
        peak = max((r[1] for r in self.rows), default=0) or 1
        for i, (name, value, text) in enumerate(self.rows):
            y = i * self.ROW
            p.setPen(QColor(self.c["text"]))
            p.drawText(QRect(0, y, name_w, self.ROW), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(name, Qt.ElideRight, name_w))
            w = max(4.0, bar_max * value / peak)
            r = QRectF(bar_left, y + self.ROW / 2 - 6, w, 12)
            path = QPainterPath()
            path.setFillRule(Qt.WindingFill)   # formes superposees : union, pas de trous
            path.addRoundedRect(r, 4, 4)
            path.addRect(QRectF(r.left(), r.top(), 4, r.height()))   # base carree a gauche
            p.setPen(Qt.NoPen)
            p.setBrush(self.color)
            p.drawPath(path.simplified())
            p.setPen(QColor(self.c["text_dim"]))
            p.drawText(QRectF(r.right() + 8, y, value_w, self.ROW),
                       Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()


class StackedBar(QWidget):
    """Barre de repartition (partie d'un tout) + legende sous la barre."""

    def __init__(self, parts, colors):
        super().__init__()
        self.parts = parts        # [(libelle, nombre, couleur)]
        self.c = colors
        self.setMinimumHeight(56)
        total = sum(n for _l, n, _c in parts)
        self.setToolTip("\n".join(f"{l} : {_fmt_int(n)} ({round(100 * n / total) if total else 0} %)"
                                  for l, n, _c in parts))

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
        fm = p.fontMetrics()
        lx = 0
        for label, n, color in self.parts:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(lx, 28, 10, 10), 2, 2)
            txt = f"{label}  {_fmt_int(n)}"
            p.setPen(QColor(self.c["text"]))
            p.drawText(QPoint(lx + 16, 38), txt)
            lx += 16 + fm.horizontalAdvance(txt) + 22
        p.end()


class ChartCard(QFrame):
    """Carte titre + graphique, avec bascule vers un tableau des valeurs."""

    def __init__(self, title, subtitle, chart, table_rows=None, headers=None):
        super().__init__()
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(6)
        head = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("cardTitle")
        head.addWidget(t)
        head.addStretch(1)
        self.stack = QStackedWidget()
        self.stack.addWidget(chart)
        if table_rows is not None:
            table = QTableWidget(len(table_rows), len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            for r, row in enumerate(table_rows):
                for col, val in enumerate(row):
                    item = QTableWidgetItem(str(val))
                    if col:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(r, col, item)
            table.setMinimumHeight(190)
            self.stack.addWidget(table)
            btn = QPushButton("Tableau")
            btn.setObjectName("toggle")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("Afficher les valeurs sous forme de tableau")
            btn.toggled.connect(lambda on: (self.stack.setCurrentIndex(1 if on else 0),
                                            btn.setText("Graphique" if on else "Tableau")))
            head.addWidget(btn)
        v.addLayout(head)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("cardSub")
            s.setWordWrap(True)
            v.addWidget(s)
        v.addWidget(self.stack)


# ---------------------------------------------------------------- fenetre

class StatsDialog(QDialog):
    def __init__(self, store, library_counts, mode, parent=None, today=None):
        """library_counts : {"unread": n, "reading": n, "finished": n}."""
        super().__init__(parent)
        self.setWindowTitle("Statistiques de lecture")
        self.resize(940, 760)
        c = theme.colors(mode)
        dc = DATA_COLORS["light" if mode == "light" else "dark"]
        today = today or dt.date.today()

        days = stats.merged_days(store.stats)
        daily = stats.daily_totals(days)
        last30 = stats.last_n_days(daily, today, 30)
        pages30 = sum(p for _d, p, _s in last30)
        secs30 = sum(s for _d, _p, s in last30)
        streak = stats.streak(daily, today)
        finished_all = stats.finished_total(store.progress)
        finished_year = stats.finished_total(store.progress, year=today.year)
        months = stats.finished_per_month(store.progress, today, 12)
        top = stats.top_series(days, n=6)
        pace = store.median_page_seconds()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll)
        host = QWidget()
        host.setObjectName("statsHost")
        scroll.setWidget(host)
        v = QVBoxLayout(host)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(14)

        title = QLabel("Statistiques de lecture")
        title.setObjectName("statsTitle")
        v.addWidget(title)
        if not days:
            hint = QLabel("L'historique des séances de lecture est enregistré depuis cette "
                          "version : les pages lues et le temps de lecture se rempliront au "
                          "fil de vos lectures. Les tomes terminés, eux, sont déjà comptés.")
            hint.setObjectName("cardSub")
            hint.setWordWrap(True)
            v.addWidget(hint)

        tiles = QGridLayout()
        tiles.setSpacing(10)
        tile_data = [
            ("Tomes terminés", _fmt_int(finished_all),
             f"dont {_fmt_int(finished_year)} en {today.year}"),
            ("Pages lues", _fmt_int(pages30), "30 derniers jours"),
            ("Temps de lecture", stats.fmt_duration(secs30), "30 derniers jours"),
            ("Jours de lecture d'affilée", _fmt_int(streak),
             "en cours" if streak else "lisez aujourd'hui pour démarrer une série"),
            ("Rythme", f"{pace:.0f} s / page".replace(".", ",") if pace else "—",
             "médiane, toutes séances" if pace else "mesuré après quelques pages"),
        ]
        for i, (lab, val, sub) in enumerate(tile_data):
            tiles.addWidget(StatTile(lab, val, sub), 0, i)
        v.addLayout(tiles)

        # --- activite quotidienne
        bars = []
        for i, (d, pages, secs) in enumerate(last30):
            label = f"{d.day}/{d.month}" if (i % 5 == 4 or i == len(last30) - 1) else ""
            tip = f"{d.strftime('%d/%m')} : {_fmt_int(pages)} pages · {stats.fmt_duration(secs)}"
            bars.append((label, pages, tip))
        v.addWidget(ChartCard(
            "Pages lues par jour", "30 derniers jours",
            BarChart(bars, dc["activity"], c, empty_text="Aucune lecture enregistrée sur la période."),
            [(d.strftime("%d/%m/%Y"), _fmt_int(p), stats.fmt_duration(s)) for d, p, s in reversed(last30)],
            ["Jour", "Pages", "Temps"]))

        # --- tomes termines par mois
        mbars = [(MONTHS_FR[m.month - 1], n,
                  f"{MONTHS_FR[m.month - 1]} {m.year} : {_fmt_int(n)} tome(s) terminé(s)")
                 for m, n in months]
        v.addWidget(ChartCard(
            "Tomes terminés par mois", "12 derniers mois",
            BarChart(mbars, dc["finished"], c, empty_text="Aucun tome terminé sur la période."),
            [(f"{MONTHS_FR[m.month - 1]} {m.year}", _fmt_int(n)) for m, n in reversed(months)],
            ["Mois", "Tomes terminés"]))

        # --- series les plus lues + repartition, cote a cote
        row = QHBoxLayout()
        row.setSpacing(14)
        if top:
            rows = [(name, secs, stats.fmt_duration(secs)) for name, secs, _p in top]
            row.addWidget(ChartCard("Séries les plus lues", "Temps de lecture, tout l'historique",
                                    HBarList(rows, dc["activity"], c)), 3)
        parts = [("Terminés", library_counts.get("finished", 0), dc["finished"]),
                 ("En cours", library_counts.get("reading", 0), dc["reading"]),
                 ("Non lus", library_counts.get("unread", 0), dc["unread"])]
        total = sum(n for _l, n, _c in parts)
        row.addWidget(ChartCard("Votre bibliothèque", f"{_fmt_int(total)} tomes",
                                StackedBar(parts, c) if total else QLabel("Bibliothèque vide.")), 2)
        v.addLayout(row)
        v.addStretch(1)

        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.setContentsMargins(22, 0, 22, 14)
        close_row.addStretch(1)
        close_row.addWidget(close)
        root.addLayout(close_row)

        self.setStyleSheet(f"""
            QDialog, #statsHost {{ background: {c['window']}; }}
            QLabel {{ color: {c['text']}; }}
            #statsTitle {{ font-size: 20px; font-weight: 700; }}
            #tile, #card {{
                background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px;
            }}
            #tileLabel {{ color: {c['text_dim']}; font-size: 12px; }}
            #tileValue {{ font-size: 24px; font-weight: 600; }}
            #tileSub, #cardSub {{ color: {c['text_dim']}; font-size: 12px; }}
            #cardTitle {{ font-size: 14px; font-weight: 700; }}
            QPushButton {{
                color: {c['text']}; background: {c['button']};
                border: 1px solid {c['border']}; border-radius: 8px; padding: 5px 14px;
            }}
            QPushButton:hover {{ background: {c['button_hover']}; }}
            QPushButton:focus {{ border: 2px solid {theme.ACCENT}; }}
            QPushButton#toggle {{ padding: 2px 10px; font-size: 12px; }}
            QTableWidget {{
                color: {c['text']}; background: {c['panel']};
                gridline-color: {c['border']}; border: none;
            }}
            QHeaderView::section {{
                color: {c['text_dim']}; background: {c['panel']};
                border: none; border-bottom: 1px solid {c['border']}; padding: 4px;
            }}
        """)
