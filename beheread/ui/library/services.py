"""Preferences, statistiques, sauvegarde et suivi AniList.

Mixin de LibraryWidget : ces methodes partagent l'etat du widget
(self.list, self.store, self._entries...) ; elles sont regroupees ici par
responsabilite pour garder chaque fichier lisible."""

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

from beheread.core.library_model import FINISHED
from beheread.core.series import normalize_name, parse_series_ex
from beheread.infra import anilist, metadata
from beheread.ui import theme

# modules extraits (voir chacun) : constantes de rendu, delegates, dialogues et
# taches d'arriere-plan. LibraryWidget (ci-dessous) orchestre le tout.
from beheread.ui.library.dialogs import PreferencesDialog
from beheread.ui.stats_view import StatsDialog


class ServicesMixin:
    # ----- preferences -----
    def open_preferences(self):
        c = theme.colors(self.store.ui_pref("theme", "dark"))
        actions = {"clear_thumbs": self._clear_thumbnails,
                   "clear_meta": self._clear_downloaded_meta,
                   "export": self._export_backup, "import": self._import_backup}
        dlg = PreferencesDialog(self.store, c, actions, self.tracker, self)
        if dlg.exec() != QDialog.Accepted:
            return
        was_online = self._online_meta()
        dlg.save()
        self._show_continue = bool(self.store.library_pref("show_continue", True))
        self._set_details_visible(bool(self.store.library_pref("show_details", False)))
        self._set_view_mode(self.store.library_pref("view_mode", "grid"))
        self._set_group_series(self.store.library_pref("group_series", False))
        if self._online_meta() and not was_online:
            self.meta.forget_failures()
        self._rebuild_list()
        self.preferencesChanged.emit()

    def _clear_thumbnails(self) -> int:
        n = self.store.clear_thumbnails()
        self.covers.clear()
        self._rebuild_list()
        return n

    def _clear_downloaded_meta(self) -> int:
        n = self.store.clear_downloaded_meta()
        self.meta.forget_failures()
        self._rebuild_list()
        return n

    # ----- service de suivi AniList, fourni par app.py -----
    def set_services(self, tracker=None):
        self.tracker = tracker
        if tracker is not None:
            tracker.seriesUpdated.connect(lambda _key: self._update_detail())

    def series_volumes_for(self, path):
        """(cle de serie, nom a chercher sur AniList, [(numero, nature,
        termine)]) pour le suivi AniList, ou None (tome isole, sans numero)."""
        def finished(p):
            prog = self.store.get_progress(p)
            return bool(prog and prog[2])

        e = self._entry_by_path.get(path)
        if e is None:   # fichier ouvert hors bibliotheque (double-clic)
            name, number, kind = parse_series_ex(Path(path).stem)
            if number is None:
                return None
            return (normalize_name(name), metadata._fold_accents(name),
                    [(number, kind, finished(path))])
        if e.detached or e.volume is None:
            return None
        key = normalize_name(e.series)
        grp = self._group_entries(self._entries).get(key) or [e]
        name = self._series_raw_name.get(key, e.series)
        return key, metadata._fold_accents(name), [(x.volume, x.kind, finished(x.path))
                                                   for x in grp]

    def _associate_anilist(self, key, path):
        """Association manuelle d'une serie a une oeuvre AniList (adresse de sa
        page ou numero), verifiee aupres d'AniList avant d'etre retenue."""
        if self.tracker is None:
            return
        name = self._series_display_name.get(key, key)
        text, ok = QInputDialog.getText(
            self, "Associer à AniList",
            f"Adresse de la page AniList de « {name} »\n"
            "(par exemple https://anilist.co/manga/30002/Berserk) ou son numéro :")
        if not ok or not text.strip():
            return
        media_id = anilist.parse_media_ref(text)
        if media_id is None:
            QMessageBox.warning(self, "Associer à AniList",
                                "Adresse non reconnue : copiez l'adresse d'une page "
                                "« anilist.co/manga/… ».")
            return
        token = self.store.anilist_token()
        if not token:
            QMessageBox.warning(self, "Associer à AniList",
                                "Reconnectez votre compte AniList dans les préférences.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            media = anilist.media_entry(token, media_id)
        except anilist.AniListError as e:
            media, error = None, str(e)
        else:
            error = "Aucune œuvre manga ne porte ce numéro sur AniList."
        finally:
            QApplication.restoreOverrideCursor()
        if media is None:
            QMessageBox.warning(self, "Associer à AniList", error)
            return
        self.tracker.associate(key, media_id, media.get("title"))
        self.tracker.resync_series(key, path)
        self._update_detail()

    # ----- statistiques -----
    def open_stats(self):
        # etat de la bibliotheque : tomes par statut, et pages qu'il reste a
        # lire dans les tomes non termines (pour le temps restant a lire)
        library = {"unread": 0, "reading": 0, "finished": 0,
                   "remaining_pages": 0, "unknown_pages": 0}
        series = {}   # empreinte -> (cle de serie, nom affiche), regroupements actuels
        titles = {}   # empreinte -> titre actuel du tome
        for e in self._entries:
            info = self._info.get(e.path) or self._entry_info(e)
            library[info.status] = library.get(info.status, 0) + 1
            titles[info.key] = e.title
            if info.series_key:
                series[info.key] = (info.series_key,
                                    self._series_display_name.get(info.series_key, e.series))
            else:
                series[info.key] = (info.key, e.title)
            if info.status == FINISHED:
                continue
            prog = self.store.get_progress(e.path)
            total = (prog[1] if prog and prog[1] else None) or self.store.page_count(e.path)
            if total:
                library["remaining_pages"] += max(0, total - (prog[0] if prog else 0))
            else:
                library["unknown_pages"] += 1
        dlg = StatsDialog(self.store, library, self.store.ui_pref("theme", "dark"), self,
                          resolve=series.get, titles=titles)
        dlg.exec()

    # ----- sauvegarde -----
    def _export_backup(self) -> str:
        default = Path.home() / f"beheread-sauvegarde-{time.strftime('%Y-%m-%d')}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Exporter la progression", str(default),
                                              "Sauvegarde Beheread (*.json)")
        if not path:
            return ""
        try:
            self.store.export_backup(path)
        except OSError as e:
            QMessageBox.warning(self, "Export impossible", str(e))
            return ""
        return f"Sauvegarde exportée : {path}"

    def _import_backup(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self, "Importer une sauvegarde", str(Path.home()),
                                              "Sauvegarde Beheread (*.json)")
        if not path:
            return ""
        try:
            result = self.store.import_backup(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Import impossible", str(e))
            return ""
        self.refresh()   # les regroupements importes peuvent changer les series
        return (f"Import terminé : {result['progress']} progression(s) et "
                f"{result['extras']} réglage(s) repris.")
