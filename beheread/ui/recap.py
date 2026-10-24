"""Bilan annuel de lecture : une image a partager (1080 x 1350, format
portrait des reseaux sociaux) et la fenetre qui la montre, l'enregistre ou
la copie. Les chiffres viennent de stats.year_recap ; ce module ne fait que
dessiner."""

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from beheread.core import stats
from beheread.i18n import fmt_int, tr, trn
from beheread.ui import style, theme
from beheread.ui.safe_text import plain

SIZE = QSize(1080, 1350)
MARGIN_X, MARGIN_Y = 84, 80
MONTH_LETTERS = "JFMAMJJASOND"   # memes initiales en anglais

# couleurs fixes : l'image se partage hors de l'application, toujours sombre
BG, TILE, BORDER = "#14161b", "#1b1e24", "#2b2f36"
TEXT, DIM = "#ffffff", "#a9b0bc"


def _font(px, bold=False):
    f = QFont()
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _hours(seconds):
    minutes = round(seconds / 60)
    return f"{minutes // 60} h" if minutes >= 60 else f"{minutes} min"


def _mix(color, other, ratio):
    a, b = QColor(color), QColor(other)
    return QColor(round(a.red() * (1 - ratio) + b.red() * ratio),
                  round(a.green() * (1 - ratio) + b.green() * ratio),
                  round(a.blue() * (1 - ratio) + b.blue() * ratio))


def render_recap(recap: stats.YearRecap, accent: str) -> QImage:
    """Image du bilan (voir la maquette 9 validee)."""
    img = QImage(SIZE, QImage.Format_RGB32)
    img.fill(QColor(BG))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    width = SIZE.width() - 2 * MARGIN_X
    x, y = MARGIN_X, MARGIN_Y

    brand = _font(26, True)
    brand.setLetterSpacing(QFont.AbsoluteSpacing, 2)
    p.setFont(brand)
    p.setPen(QColor(accent))
    p.drawText(QRect(x, y, width, 34), Qt.AlignLeft | Qt.AlignVCenter, "BEHEREAD")
    y += 44
    p.setFont(_font(72, True))
    p.setPen(QColor(TEXT))
    title_h = 2 * p.fontMetrics().lineSpacing()
    p.drawText(QRect(x, y, width, title_h), Qt.AlignLeft | Qt.AlignTop,
               tr("Mon année {year}\nde lecture", year=recap.year))
    y += title_h + 24

    # quatre chiffres : temps, tomes, jour prefere, record
    if recap.favorite_weekday is not None:
        day = tr(stats.WEEKDAYS_FR[recap.favorite_weekday]).capitalize()
        day_label = (tr("jour de lecture préféré") + "\n"
                     + tr("{n} pages en moyenne", n=f"{recap.favorite_pages:.0f}"))
    else:
        day, day_label = "—", tr("jour de lecture préféré")
    # tomes seuls ; les chapitres termines en dessous
    volumes = recap.finished - recap.finished_chapters
    volumes_label = tr("tome terminé") if volumes == 1 else tr("tomes terminés")
    if recap.finished_chapters:
        volumes_label += "\n" + trn(recap.finished_chapters, "+ {n} chapitre", "+ {n} chapitres")
    tiles = [(_hours(recap.seconds), tr("de lecture")),
             (fmt_int(volumes), volumes_label),
             (day, day_label),
             (trn(recap.best_streak, "{n} jour", "{n} jours"),
              tr("de lecture d'affilée, mon record"))]
    gap, tile_h = 22, 160
    tile_w = (width - gap) // 2
    for i, (value, label) in enumerate(tiles):
        tx, ty = x + (i % 2) * (tile_w + gap), y + (i // 2) * (tile_h + gap)
        p.setPen(QColor(BORDER))
        p.setBrush(QColor(TILE))
        p.drawRoundedRect(QRectF(tx, ty, tile_w, tile_h), 18, 18)
        p.setFont(_font(64 if len(value) <= 9 else 52, True))
        p.setPen(QColor(TEXT))
        p.drawText(QRect(tx + 28, ty + 16, tile_w - 56, 76), Qt.AlignLeft | Qt.AlignVCenter, value)
        p.setFont(_font(22))
        p.setPen(QColor(DIM))
        p.drawText(QRect(tx + 28, ty + 94, tile_w - 56, 60),
                   Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, label)
    y += 2 * tile_h + gap + 36

    p.setFont(_font(30, True))
    p.setPen(QColor(TEXT))
    p.drawText(QRect(x, y, width, 40), Qt.AlignLeft | Qt.AlignVCenter, tr("Mes séries de l'année"))
    y += 56
    longest = max((s.seconds for s in recap.series), default=0) or 1
    for s in recap.series:
        p.setFont(_font(24))
        p.setPen(QColor(TEXT))
        name = p.fontMetrics().elidedText(s.name, Qt.ElideRight, width - 280)
        p.drawText(QRect(x, y, width, 32), Qt.AlignLeft | Qt.AlignVCenter, name)
        p.setPen(QColor(DIM))
        detail = f"{_hours(s.seconds)} · " + trn(s.finished, "{n} tome", "{n} tomes")
        p.drawText(QRect(x, y, width, 32), Qt.AlignRight | Qt.AlignVCenter, detail)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(accent))
        p.drawRoundedRect(QRectF(x, y + 38, max(14, width * s.seconds / longest), 12), 6, 6)
        y += 64
    if not recap.series:
        p.setFont(_font(24))
        p.setPen(QColor(DIM))
        p.drawText(QRect(x, y, width, 32), Qt.AlignLeft | Qt.AlignVCenter, tr("Aucune lecture cette année"))
        y += 64
    y += 16 + 64 * (3 - max(1, len(recap.series)))   # meme place pour 1 a 3 series

    p.setFont(_font(30, True))
    p.setPen(QColor(TEXT))
    p.drawText(QRect(x, y, width, 40), Qt.AlignLeft | Qt.AlignVCenter, tr("Mois par mois"))
    y += 56
    chart_h, col_gap = 140, 12
    col_w = (width - 11 * col_gap) / 12
    top_month = max(range(12), key=lambda m: recap.months[m])
    peak = recap.months[top_month] or 1
    dim_accent = _mix(accent, BG, 0.45)
    for m, seconds in enumerate(recap.months):
        h = chart_h * seconds / peak
        cx = x + m * (col_w + col_gap)
        if h > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(accent) if m == top_month else dim_accent)
            p.drawRoundedRect(QRectF(cx, y + chart_h - h, col_w, h), 6, 6)
        p.setFont(_font(18, m == top_month and recap.months[m] > 0))
        p.setPen(QColor(TEXT if m == top_month and recap.months[m] > 0 else DIM))
        p.drawText(QRectF(cx, y + chart_h + 10, col_w, 26), Qt.AlignHCenter | Qt.AlignTop,
                   MONTH_LETTERS[m])

    p.setFont(_font(20))
    p.setPen(QColor(DIM))
    p.drawText(QRect(x, SIZE.height() - MARGIN_Y - 30, width, 30), Qt.AlignLeft | Qt.AlignVCenter,
               tr("Lu avec Beheread, lecteur de mangas hors ligne"))
    p.end()
    return img


class RecapDialog(QDialog):
    """Apercu du bilan, choix de l'annee, enregistrement et copie."""

    PREVIEW = QSize(432, 540)

    def __init__(self, log, colors, today=None, resolve=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Bilan de l'année"))
        self.log, self.resolve = log, resolve
        self.today = today or dt.date.today()
        self.image = None
        self.setStyleSheet(f"""
            QDialog {{ background: {colors['window']}; }}
            QLabel {{ color: {colors['text']}; }}
            QComboBox {{ color: {colors['text']}; background: {colors['panel']};
                         border: 1px solid {colors['border']}; border-radius: 6px; padding: 4px 8px; }}
            QPushButton {{ color: {colors['text']}; background: {colors['button']};
                           border: 1px solid {colors['border']}; border-radius: 8px; padding: 6px 14px; }}
            QPushButton:hover {{ background: {colors['button_hover']}; }}
            """ + style.primary_button("QPushButton#primary"))
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)
        top = QHBoxLayout()
        label = QLabel(tr("Année"))
        top.addWidget(label)
        self.year = QComboBox()
        for year in stats.recap_years(log, self.today) or [self.today.year]:
            self.year.addItem(str(year), year)
        label.setBuddy(self.year)
        self.year.currentIndexChanged.connect(lambda _i: self._render())
        top.addWidget(self.year)
        top.addStretch(1)
        root.addLayout(top)
        self.preview = QLabel()
        self.preview.setFixedSize(self.PREVIEW)
        self.preview.setAccessibleName(tr("Aperçu du bilan"))
        root.addWidget(self.preview, 0, Qt.AlignHCenter)
        row = QHBoxLayout()
        save = QPushButton(tr("Enregistrer l'image…"))
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        copy = QPushButton(tr("Copier"))
        copy.clicked.connect(self._copy)
        close = QPushButton(tr("Fermer"))
        close.clicked.connect(self.accept)
        row.addWidget(save)
        row.addWidget(copy)
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)
        self._render()

    def _render(self):
        recap = stats.year_recap(self.log, self.year.currentData(), self.today, self.resolve)
        self.image = render_recap(recap, theme.ACCENT)
        dpr = self.devicePixelRatioF()
        pm = QPixmap.fromImage(self.image).scaled(self.PREVIEW * dpr, Qt.KeepAspectRatio,
                                                  Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self.preview.setPixmap(pm)

    def _save(self):
        default = Path.home() / f"beheread-bilan-{self.year.currentData()}.png"
        path, _ = QFileDialog.getSaveFileName(self, tr("Enregistrer le bilan"), str(default),
                                              tr("Image PNG (*.png)"))
        if path and not self.image.save(path, "PNG"):
            QMessageBox.warning(self, tr("Enregistrement impossible"),
                                plain(tr("L'image n'a pas pu être enregistrée :\n{path}",
                                         path=path)))

    def _copy(self):
        QApplication.clipboard().setImage(self.image)
