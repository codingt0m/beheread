"""Capture d'une zone de la planche, a la maniere de Win + Maj + S.

Le raccourci (reglable, P par defaut) assombrit le lecteur ; on
trace un rectangle a la souris, et la zone est copiee dans le presse-papiers
et enregistree en PNG (dossier reglable, Images/Beheread par defaut).

La capture est prise dans le scan lui-meme, a sa resolution d'origine, et non
a l'ecran : une case reste nette, sans le fond ni l'Ambilight. En double page,
une zone a cheval sur les deux pages donne une seule image qui les assemble.

Mixin de ReaderWidget pour le branchement ; l'assemblage (compose_capture) et
le nommage des fichiers sont des fonctions pures, testees isolement.

Performances : l'assemblage (quelques dizaines de ms pour une double page
entiere) et la copie restent dans le fil de l'interface ; l'encodage PNG, qui
prend jusqu'a deux secondes pour une double page en pleine resolution, se fait
dans un fil a part (CaptureSaver), une capture apres l'autre. Pendant la
selection, seule la partie de l'ecran qui change est redessinee."""

import logging
import re
import time
from pathlib import Path

from PySide6.QtCore import (
    QKeyCombination,
    QObject,
    QPointF,
    QRect,
    QRectF,
    QRunnable,
    QSize,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from beheread import platforms
from beheread.i18n import tr
from beheread.ui import keys, theme

DEFAULT_SHORTCUT = "P"             # QKeySequence.PortableText
# premier raccourci par defaut, trop proche de S (decalage) : vaut le nouveau
_OLD_DEFAULTS = ("Ctrl+Shift+S",)
MIN_DRAG = 6                        # px : en deca, un clic (annule la capture)
TOAST_MS = 5000
MAX_SIDE = 16384                    # garde-fou : image assemblee demesuree


# ------------------------------------------------------------ fonctions pures

def default_capture_dir() -> str:
    """Images/Beheread de l'utilisateur."""
    pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    return str(Path(pictures or Path.home()) / "Beheread")


def capture_dir(store) -> str:
    return store.reader_pref("capture_dir") or default_capture_dir()


def shortcut_text(store) -> str:
    """Raccourci de capture des preferences, en texte portable (vide =
    desactive ; None enregistre = celui par defaut)."""
    text = store.reader_pref("capture_shortcut")
    return DEFAULT_SHORTCUT if text is None or text in _OLD_DEFAULTS else text


def shortcut_sequence(store) -> QKeySequence:
    return QKeySequence(shortcut_text(store), QKeySequence.PortableText)


def shortcut_label(text: str) -> str:
    """Raccourci (texte portable « Ctrl+Shift+S ») ecrit a la maniere des
    textes de Beheread (« Ctrl + Maj + S »), a passer a keys.label."""
    seq = QKeySequence(text or "", QKeySequence.PortableText)
    if seq.isEmpty():
        return ""
    combo = seq[0]
    mods = combo.keyboardModifiers()
    parts = [name for flag, name in ((Qt.ControlModifier, "Ctrl"), (Qt.AltModifier, "Alt"),
                                     (Qt.ShiftModifier, "Maj"), (Qt.MetaModifier, "Meta"))
             if mods & flag]
    parts.append(QKeySequence(combo.key()).toString(QKeySequence.PortableText))
    return " + ".join(parts)


def matches(event, sequence: QKeySequence) -> bool:
    """La touche pressee est-elle ce raccourci ? (le pave numerique compte
    comme le clavier principal)"""
    if sequence.isEmpty():
        return False
    mods = event.modifiers() & ~Qt.KeypadModifier
    pressed = QKeySequence(QKeyCombination(mods, Qt.Key(event.key())))
    return pressed == QKeySequence(sequence[0])


def capture_filename(stem: str, page: int, now=None) -> str:
    """« Tome 3 - p042 - 2026-11-20 15-30-12.png » : nom du tome, page (de
    1), date ; caracteres interdits sous Windows retires."""
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", stem or "")
    stem = re.sub(r"\s+", " ", stem).strip(" .") or "Beheread"
    stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(now))
    return f"{stem[:120]} - p{page:03d} - {stamp}.png"


def unique_path(folder: Path, name: str) -> Path:
    path = folder / name
    n = 2
    while path.exists():
        path = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    return path


def compose_capture(selection: QRectF, placed) -> QImage:
    """Image de la zone `selection` (coordonnees de l'ecran) prise dans les
    pages affichees. `placed` : [(image source, rectangle source, rectangle a
    l'ecran)] - le rectangle source est la partie de l'image affichee (marges
    rognees). Echelle : celle de la page la plus detaillee de la zone, pour ne
    rien perdre de sa resolution. Image nulle si la zone ne touche aucune page."""
    hits = []
    for img, src, screen in placed:
        part = selection.intersected(screen)
        if img is None or img.isNull() or part.isEmpty() or screen.width() <= 0:
            continue
        hits.append((img, QRectF(src), screen, part))
    if not hits:
        return QImage()
    # zone utile : la selection rognee aux pages (pas de bande du fond)
    area = QRectF(hits[0][3])
    for *_rest, part in hits[1:]:
        area = area.united(part)
    scale = max(src.width() / screen.width() for _img, src, screen, _p in hits)
    scale = min(scale, MAX_SIDE / max(area.width(), area.height()))
    out = QImage(QSize(max(1, round(area.width() * scale)), max(1, round(area.height() * scale))),
                 QImage.Format_RGB32)
    out.fill(QColor("white"))
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    for img, src, screen, part in hits:
        sx = src.width() / screen.width()
        sy = src.height() / screen.height()
        source = QRectF(src.x() + (part.x() - screen.x()) * sx,
                        src.y() + (part.y() - screen.y()) * sy,
                        part.width() * sx, part.height() * sy)
        target = QRectF((part.x() - area.x()) * scale, (part.y() - area.y()) * scale,
                        part.width() * scale, part.height() * scale)
        p.drawImage(target, img, source)
    p.end()
    return out


def output_size(selection: QRectF, placed) -> QSize:
    """Taille en pixels de l'image que donnerait cette zone (affichee
    pendant la selection), sans l'assembler."""
    hits = [(QRectF(src), screen, selection.intersected(screen))
            for img, src, screen in placed if img is not None and not img.isNull()]
    hits = [h for h in hits if not h[2].isEmpty() and h[1].width() > 0]
    if not hits:
        return QSize()
    area = QRectF(hits[0][2])
    for *_rest, part in hits[1:]:
        area = area.united(part)
    scale = max(src.width() / screen.width() for src, screen, _p in hits)
    scale = min(scale, MAX_SIDE / max(area.width(), area.height()))
    return QSize(max(1, round(area.width() * scale)), max(1, round(area.height() * scale)))


# ------------------------------------------------------------ calque de selection

class CaptureOverlay(QWidget):
    """Calque pose sur le lecteur pendant une capture : fond assombri, zone
    tracee a la couleur d'accentuation avec sa taille en pixels. Echap ou un
    simple clic annule ; un clic droit prend toutes les pages affichees."""

    selected = Signal(QRectF)
    cancelled = Signal()

    def __init__(self, parent, size_of):
        super().__init__(parent)
        self._size_of = size_of       # QRectF -> QSize (taille de l'image produite)
        self._start = None
        self._rect = QRectF()
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName(tr("Capture d'une zone"))
        self.hide()

    def begin(self):
        self._start = None
        self._rect = QRectF()
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.update()

    def _finish(self, rect=None):
        self.hide()
        self.parentWidget().setFocus()
        if rect is None:
            self.cancelled.emit()
        else:
            self.selected.emit(rect)

    # --- souris / clavier
    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._finish(QRectF(self.rect()))
        elif event.button() == Qt.LeftButton:
            self._start = event.position()
            self._rect = QRectF()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            old = self._rect
            self._rect = QRectF(self._start, event.position()).normalized()
            # seule la zone qui change (ancien et nouveau cadre, avec leur
            # badge de taille) est redessinee, pas tout l'ecran
            self.update(self._dirty(old).united(self._dirty(self._rect)))
        event.accept()

    @staticmethod
    def _dirty(r):
        if r.isEmpty():
            return QRect()
        return r.adjusted(-8, -40, 160, 40).toAlignedRect()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._start is None:
            return
        rect = QRectF(self._start, event.position()).normalized()
        self._start = None
        dragged = rect.width() >= MIN_DRAG and rect.height() >= MIN_DRAG
        self._finish(rect if dragged else None)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._finish()
        event.accept()   # aucune touche du lecteur pendant la selection

    def wheelEvent(self, event):
        event.accept()

    # --- rendu
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shade = QColor(0, 0, 0, 140)
        full = QRectF(self.rect())
        r = self._rect
        if r.isEmpty():
            p.fillRect(full, shade)
        else:
            # quatre bandes autour de la zone, laissee intacte
            p.fillRect(QRectF(0, 0, full.width(), r.top()), shade)
            p.fillRect(QRectF(0, r.bottom(), full.width(), full.height() - r.bottom()), shade)
            p.fillRect(QRectF(0, r.top(), r.left(), r.height()), shade)
            p.fillRect(QRectF(r.right(), r.top(), full.width() - r.right(), r.height()), shade)
            accent = QColor(theme.ACCENT)
            p.setPen(QPen(accent, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r.adjusted(-1, -1, 1, 1))
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            for corner in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
                p.drawRoundedRect(QRectF(corner - QPointF(4, 4), QSize(8, 8)), 2, 2)
            size = self._size_of(r)
            if size.isValid():
                self._draw_badge(p, f"{size.width()} × {size.height()}", r)
        self._draw_tip(p)

    def _badge_font(self, p, px, bold=True):
        font = p.font()
        font.setPixelSize(px)
        font.setBold(bold)
        p.setFont(font)
        return p.fontMetrics()

    def _draw_badge(self, p, text, r):
        fm = self._badge_font(p, 12)
        w, h = fm.horizontalAdvance(text) + 14, fm.height() + 6
        y = r.top() - h - 6 if r.top() - h - 6 >= 0 else r.bottom() + 6
        x = min(max(0.0, r.left()), self.width() - w)
        box = QRectF(x, y, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(box, 5, 5)
        p.setPen(QColor(theme.ON_ACCENT))
        p.drawText(box, Qt.AlignCenter, text)

    def _draw_tip(self, p):
        text = "   ·   ".join((tr("Tracez la zone à capturer"),
                               tr("{key} pour annuler", key=keys.label("Échap")),
                               tr("Clic droit : toutes les pages affichées")))
        fm = self._badge_font(p, 13, bold=False)
        w = min(fm.horizontalAdvance(text) + 28, self.width() - 24)
        h = fm.height() + 14
        box = QRectF((self.width() - w) / 2, 16, w, h)
        c = theme.colors(_mode(self))
        p.setPen(QColor(c["border"]))
        p.setBrush(QColor(c["hud_bg"]))
        p.drawRoundedRect(box, 10, 10)
        p.setPen(QColor(c["text"]))
        p.drawText(box, Qt.AlignCenter, fm.elidedText(text, Qt.ElideRight, int(w - 20)))


def _mode(widget):
    store = getattr(widget.parentWidget(), "store", None)
    return store.ui_pref("theme", "dark") if store is not None else "dark"


# ------------------------------------------------------------ confirmation

class CaptureToast(QFrame):
    """Vignette de la capture en haut a droite, quelques secondes : ce qui a
    ete fait (copiee, enregistree) et l'acces au dossier."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("captureToast")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 12, 8)
        row.setSpacing(12)
        self.thumb = QLabel(self)
        self.thumb.setFixedSize(64, 64)
        self.thumb.setAlignment(Qt.AlignCenter)
        row.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel(self)
        self.title.setObjectName("captureTitle")
        self.detail = QLabel(self)
        self.detail.setObjectName("captureDetail")
        self.detail.setTextFormat(Qt.PlainText)
        col.addWidget(self.title)
        col.addWidget(self.detail)
        self.reveal = QPushButton(tr("Afficher le dossier"), self)
        self.reveal.setCursor(Qt.PointingHandCursor)
        self.reveal.setFocusPolicy(Qt.NoFocus)
        self.reveal.clicked.connect(self._reveal)
        col.addWidget(self.reveal, 0, Qt.AlignLeft)
        row.addLayout(col)
        self._path = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def apply_colors(self, c):
        self.setStyleSheet(
            f"#captureToast {{ background: {c['hud_bg']}; border: 1px solid {c['border']};"
            " border-radius: 12px; }"
            f"#captureTitle {{ color: {c['text']}; font-size: 13px; font-weight: 600; }}"
            f"#captureDetail {{ color: {c['text_dim']}; font-size: 12px; }}"
            f"QPushButton {{ color: {theme.ON_ACCENT}; background: {theme.ACCENT};"
            " border: none; border-radius: 9px; padding: 4px 8px; margin-top: 4px;"
            " font-size: 12px; font-weight: 600; }"
            f"QPushButton:hover {{ background: {theme.ACCENT_HOVER}; }}")

    def show_result(self, image: QImage, title: str, detail: str, path=None):
        # vignette reduite avant conversion : pas de pixmap de la taille de la capture
        dpr = self.devicePixelRatioF()
        pm = QPixmap.fromImage(image.scaled(self.thumb.size() * dpr, Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))
        pm.setDevicePixelRatio(dpr)
        self.thumb.setPixmap(pm)
        self.update_result(title, detail, path)

    def update_result(self, title: str, detail: str, path=None):
        """Nouveau texte (fin de l'enregistrement), meme vignette."""
        self.title.setText(title)
        self.detail.setText(detail)
        self._path = path
        self.reveal.setVisible(path is not None)
        self.adjustSize()
        self.place()
        self.show()
        self.raise_()
        self._timer.start(TOAST_MS)

    def place(self):
        parent = self.parentWidget()
        self.move(parent.width() - self.width() - 18, 18)

    def _reveal(self):
        if self._path is not None:
            platforms.reveal_in_file_manager(str(self._path))
        self.hide()


# ------------------------------------------------------------ enregistrement

class _SaverSignals(QObject):
    done = Signal(int, object, str)   # numero de capture, Path ou None, dossier en echec


class CaptureSaver(QRunnable):
    """Encode et ecrit la capture en PNG hors du fil de l'interface. Le nom
    est choisi ici (unique_path) : les captures passent une par une
    (SAVE_POOL a un seul fil), deux captures de la meme seconde ne se
    disputent donc jamais le meme nom."""

    def __init__(self, ticket, image, folder, stem, page):
        super().__init__()
        self.ticket, self.image, self.folder = ticket, image, folder
        self.stem, self.page = stem, page
        self.signals = _SaverSignals()

    def run(self):
        try:
            folder = Path(self.folder)
            folder.mkdir(parents=True, exist_ok=True)
            path = unique_path(folder, capture_filename(self.stem, self.page))
            image = self.image
            if image.isGrayscale():   # scan en noir et blanc : PNG bien plus leger
                image = image.convertToFormat(QImage.Format_Grayscale8)
            if not image.save(str(path), "PNG"):
                raise OSError(f"écriture impossible : {path}")
        except OSError:
            logging.warning("Capture non enregistree", exc_info=True)
            self.signals.done.emit(self.ticket, None, self.folder)
            return
        self.signals.done.emit(self.ticket, path, "")


SAVE_POOL = QThreadPool()
SAVE_POOL.setMaxThreadCount(1)


# ------------------------------------------------------------ branchement au lecteur

class CaptureMixin:
    def _build_capture(self):
        self._placed_pages = []   # [(index, rectangle source, rectangle ecran)], voir _draw_pages
        self._capture_overlay = CaptureOverlay(self, self._capture_size)
        self._capture_overlay.selected.connect(self._on_capture_selected)
        self._capture_toast = CaptureToast(self)
        self._capture_ticket = 0      # derniere capture : seule elle met a jour la vignette
        self._capture_savers = set()  # enregistrements en cours (gardes en vie)
        self._capture_copied = False
        self._capture_px = ""

    def _placed_images(self):
        out = []
        for index, src, screen in self._placed_pages:
            img = self.cache.get(index)
            if img is not None and not img.isNull():
                out.append((img, src if src is not None else QRect(img.rect()), screen))
        return out

    def _capture_size(self, rect):
        return output_size(rect, self._placed_images())

    def start_capture(self):
        if not self._placed_images():
            return   # page en chargement ou illisible : rien a capturer
        self._capture_toast.hide()
        self._hide_chrome()
        self._capture_overlay.begin()

    def _on_capture_selected(self, rect):
        image = compose_capture(rect, self._placed_images())
        if image.isNull():
            return
        store = self.store
        copy = store.reader_pref("capture_clipboard", True)
        save = store.reader_pref("capture_save", True)
        if copy:
            QGuiApplication.clipboard().setImage(image)
        self._capture_ticket += 1
        self._capture_copied = copy
        self._capture_px = f"{image.width()} × {image.height()} px"
        if save:
            # vignette tout de suite ; texte final a la fin de l'enregistrement
            self._capture_toast.show_result(
                image, tr("Capture copiée") if copy else tr("Capture"), tr("Enregistrement…"))
            page = min(i for i, _src, _screen in self._placed_pages) + 1
            saver = CaptureSaver(self._capture_ticket, image, capture_dir(store),
                                 Path(self.path).stem, page)
            saver.setAutoDelete(False)
            self._capture_savers.add(saver)
            saver.signals.done.connect(self._on_capture_saved)
            SAVE_POOL.start(saver)
        elif copy:
            self._capture_toast.show_result(image, tr("Capture copiée"), self._capture_px)
        else:
            self._capture_toast.show_result(
                image, tr("Capture faite, mais ni copiée ni enregistrée"),
                tr("Voir les préférences, Lecture"))

    def _on_capture_saved(self, ticket, path, failed_folder):
        self._capture_savers = {s for s in self._capture_savers if s.ticket != ticket}
        if ticket != self._capture_ticket or not self._capture_toast.isVisible():
            return   # une capture plus recente occupe deja la vignette
        copy = self._capture_copied
        if path is None:
            title = tr("Capture copiée, non enregistrée") if copy else tr("Capture non enregistrée")
            detail = tr("Dossier inaccessible : {folder}", folder=failed_folder)
        else:
            title = tr("Capture copiée et enregistrée") if copy else tr("Capture enregistrée")
            detail = f"{self._capture_px} · {path.name}"
        self._capture_toast.update_result(title, detail, path)
