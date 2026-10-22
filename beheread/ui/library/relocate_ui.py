"""Deplacer des tomes, des chapitres ou une serie vers un autre dossier
source de la bibliotheque (ex. du disque local vers iCloud Drive).

Mixin de LibraryWidget. Les fichiers gardent leur sous-dossier et sont
deplaces en arriere-plan (MoveWorker) ; la progression, les couvertures
choisies et les tomes virtuels, indexes par contenu, les suivent. Un fichier
ouvert dans le lecteur est deplace a sa fermeture.
"""

import os
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from beheread.core import units
from beheread.core.series import normalize_name
from beheread.i18n import tr
from beheread.infra import relocate, virtual
from beheread.ui import theme
from beheread.ui.library.dialogs import _dialog_css, format_size
from beheread.ui.library.workers import MoveWorker
from beheread.ui.safe_text import plain


def _label(text, hint=False):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)   # noms de serie et chemins : non fiables
    label.setWordWrap(True)
    if hint:
        label.setObjectName("hint")
    return label


class MoveConfirmDialog(QDialog):
    """« Deplacer vers … » : ce qui part, sa taille et sa destination."""

    def __init__(self, folder, what, size, target, colors, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Déplacer vers un dossier"))
        self.setMinimumWidth(480)
        self.setStyleSheet(_dialog_css(colors))
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)
        heading = _label(tr("Déplacer vers {folder}", folder=folder))
        heading.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(heading)
        root.addWidget(_label(f"{what} · {size}" if size else what))
        root.addWidget(_label(tr("Destination : {path}", path=target), hint=True))
        root.addWidget(_label(tr("Les fichiers gardent leur sous-dossier. La lecture, les "
                                 "couvertures choisies et les tomes virtuels suivent les "
                                 "fichiers."), hint=True))
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("Annuler"))
        cancel.clicked.connect(self.reject)
        ok = QPushButton(tr("Déplacer"))
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        root.addLayout(row)


class MoveProgressDialog(QDialog):
    """« Deplacement en cours… » : fichier en cours, barre, arret apres le
    fichier en cours. Non modale : on peut continuer a lire."""

    def __init__(self, total, cancel, colors, parent=None):
        super().__init__(parent)
        self.total = total
        self.setWindowTitle(tr("Déplacement en cours…"))
        self.setMinimumWidth(460)
        self.setStyleSheet(_dialog_css(colors) + f"""
            QProgressBar {{ background: {colors['button']}; border: none; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {theme.ACCENT}; border-radius: 4px; }}""")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)
        heading = _label(tr("Déplacement en cours…"))
        heading.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(heading)
        self.current = _label("")
        root.addWidget(self.current)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setRange(0, total)
        root.addWidget(self.bar)
        root.addWidget(_label(tr("Vous pouvez continuer à lire pendant ce temps. Un fichier "
                                 "ouvert dans le lecteur est déplacé à sa fermeture."),
                              hint=True))
        row = QHBoxLayout()
        row.addStretch(1)
        self.stop = QPushButton(tr("Arrêter après ce fichier"))
        self.stop.clicked.connect(cancel.set)
        self.stop.clicked.connect(lambda: self.stop.setEnabled(False))
        row.addWidget(self.stop)
        root.addLayout(row)

    def set_step(self, index, name):
        self.current.setText(tr("{name} · {n} sur {total}", name=name, n=index + 1,
                                total=self.total))
        self.bar.setValue(index)


class RelocateMixin:
    # ------------------------------------------------------------ menus
    def _add_move_menu(self, menu, paths, series=False):
        """Sous-menu « Deplacer vers un dossier › » (dossiers sources de la
        bibliotheque, l'actuel grise) ; {action: dossier}, vide si rien a
        proposer (fichiers d'un serveur ou virtuels, un seul dossier)."""
        paths = self._movable(paths)
        folders = self.store.folders()
        if not paths or len(folders) < 2:
            return {}
        sub = menu.addMenu(tr("Déplacer la série vers un dossier") if series
                           else tr("Déplacer vers un dossier"))
        roots = {relocate.source_root(p, folders) for p in paths}
        actions = {}
        for folder in folders:
            current = roots == {folder}
            act = sub.addAction(f"{folder}   ·   " + tr("actuel") if current else folder)
            act.setEnabled(not current)
            actions[act] = folder
        return actions

    def _movable(self, paths):
        """Fichiers locaux seulement : ni tome d'un serveur, ni tome virtuel
        (ses chapitres, eux, se deplacent)."""
        return [p for p in paths if p and not self._is_remote(p) and not virtual.is_virtual(p)]

    # ------------------------------------------------------------ deplacement
    def _move_paths(self, paths, folder):
        folders = self.store.folders()
        pairs = relocate.plan(self._movable(paths), folders, folder)
        if not pairs:
            return
        entries = [self._entry_by_path.get(src) for src, _dst in pairs]
        chapters = sum(1 for e in entries if e is not None and units.is_chapter(self._unit(e)))
        what = units.count_text(len(pairs) - chapters, chapters)
        series = {normalize_name(e.series) for e in entries if e is not None}
        if len(series) == 1 and len(pairs) > 1:
            key = next(iter(series))
            what = tr("{items} de « {series} »", items=what,
                      series=self._series_display_name.get(key, key))
        size = 0
        for src, _dst in pairs:
            try:
                size += os.path.getsize(src)
            except OSError:
                pass
        parents = {str(Path(dst).parent) for _src, dst in pairs}
        target = parents.pop() if len(parents) == 1 else folder
        colors = theme.colors(self.store.ui_pref("theme", "dark"))
        dlg = MoveConfirmDialog(folder, what, format_size(size) if size else "", target,
                                colors, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._start_move(pairs, colors)

    def _start_move(self, pairs, colors=None, quiet=False):
        """Lance le deplacement en arriere-plan ; `quiet` : sans fenetre de
        progression (fichiers retenus a la fermeture du lecteur)."""
        cancel = threading.Event()
        worker = MoveWorker(pairs, cancel)
        progress = None
        if not quiet:
            progress = MoveProgressDialog(len(pairs), cancel, colors, self)
            worker.signals.step.connect(progress.set_step)
            progress.show()
        worker.signals.done.connect(
            lambda result: self._on_moved(result, progress, quiet, worker))
        self._move_jobs.append(worker)   # garde une reference (sinon GC)
        QThreadPool.globalInstance().start(worker)

    def _on_moved(self, result, progress, quiet, worker):
        self._move_jobs = [w for w in self._move_jobs if w is not worker]
        if progress is not None:
            progress.close()
        for src, dst in result["moved"]:
            self.store.note_renamed(src, dst)
            self.covers.rename(src, dst)
        # fichiers ouverts (lecteur) : deplaces quand ils seront liberes
        self._deferred_moves.extend(result["busy"])
        if result["moved"]:
            self.store.flush()
            self.refresh()
        problems = []
        if result["exists"]:
            problems.append(tr("Déjà présents à destination, laissés en place :") + "\n"
                            + "\n".join(f"- {Path(src).name}" for src, _dst in result["exists"]))
        if result["errors"]:
            problems.append(tr("Non déplacés :") + "\n"
                            + "\n".join(f"- {Path(src).name} : {msg}"
                                        for src, msg in result["errors"]))
        if result["busy"] and not quiet:
            problems.append(tr("Ouverts dans le lecteur, déplacés à sa fermeture :") + "\n"
                            + "\n".join(f"- {Path(src).name}" for src, _dst in result["busy"]))
        if problems:
            QMessageBox.information(self, tr("Déplacement"), plain("\n\n".join(problems)))

    def _retry_deferred_moves(self):
        """Lecteur ferme : les fichiers qu'il tenait sont deplaces a leur
        tour (silencieusement, sauf probleme)."""
        if not self._deferred_moves:
            return
        pairs, self._deferred_moves = self._deferred_moves, []
        self._start_move(pairs, quiet=True)
