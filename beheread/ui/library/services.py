"""Preferences, statistiques, sauvegarde et suivi AniList.

Mixin de LibraryWidget : ces methodes partagent l'etat du widget
(self.list, self.store, self._entries...) ; elles sont regroupees ici par
responsabilite pour garder chaque fichier lisible."""

import time
from pathlib import Path

from PySide6.QtCore import QLocale, Qt, QThreadPool
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
)

from beheread import i18n
from beheread.core import series_stats, units
from beheread.core.anilist_track import ONESHOT
from beheread.core.library_model import FINISHED, aggregate_series_info
from beheread.core.series import normalize_name, parse_path
from beheread.i18n import tr, trn
from beheread.infra import anilist, archive, metadata, updates, virtual
from beheread.ui import theme

# modules extraits (voir chacun) : constantes de rendu, delegates, dialogues et
# taches d'arriere-plan. LibraryWidget (ci-dessous) orchestre le tout.
from beheread.ui.library import prompt
from beheread.ui.library.dialogs import PreferencesDialog
from beheread.ui.library.workers import CallWorker
from beheread.ui.safe_text import plain
from beheread.ui.stats_view import StatsDialog


class ServicesMixin:
    # ----- preferences -----
    def open_preferences(self):
        c = theme.colors(self.store.ui_pref("theme", "dark"))
        actions = {"clear_thumbs": self._clear_thumbnails,
                   "clear_meta": self._clear_downloaded_meta,
                   "export": self._export_backup, "import": self._import_backup,
                   "export_csv": self._export_reading_csv,
                   "check_updates": lambda report: self.check_updates(True, report),
                   "manage_folders": self.manage_folders}
        dlg = PreferencesDialog(self.store, c, actions, self.tracker, self, servers=self.servers,
                                cloud_sync=self.cloud_sync)
        system = QLocale.system().name()
        old_language = i18n.resolve(self.store.ui_pref("language", "system"), system)
        # chaque reglage s'applique des qu'il change (maquette M2)
        self._applied_prefs = self._prefs_snapshot()
        dlg.applied.connect(self._apply_preferences)
        dlg.exec()
        # langue effectivement differente (« systeme » peut valoir la langue
        # choisie avant) : redemarrage a la fermeture, les textes etant
        # traduits a la creation des fenetres
        if i18n.resolve(self.store.ui_pref("language", "system"), system) != old_language:
            self.restartRequested.emit()

    def _prefs_snapshot(self):
        return self._online_meta(), bool(self.store.ui_pref("servers_enabled", False))

    def _apply_preferences(self):
        """Applique les preferences que le dialogue vient d'enregistrer."""
        was_online, servers_were_on = self._applied_prefs
        self._applied_prefs = self._prefs_snapshot()
        if self._online_meta() and not was_online:
            self.meta.forget_failures()
        archive.set_extra_page_words(self.store.library_pref("extra_page_words"))
        if self.servers is not None and self._applied_prefs[1] != servers_were_on:
            self.servers.reload()   # option activee ou desactivee
        self._rebuild_list()
        self.preferencesChanged.emit()

    def _clear_thumbnails(self) -> int:
        n = self.store.clear_thumbnails()
        self.covers.clear()
        self._rebuild_list()
        return n

    def _clear_downloaded_meta(self) -> int:
        n = self.store.clear_downloaded_meta()
        metadata.clear_series_memo()
        self.meta.forget_failures()
        self._rebuild_list()
        return n

    # ----- services fournis par app.py : suivi AniList, synchronisation -----
    def set_services(self, tracker=None, cloud_sync=None):
        self.tracker = tracker
        self.cloud_sync = cloud_sync
        if tracker is not None:
            tracker.seriesUpdated.connect(lambda _key: self._update_detail())

    def series_volumes_for(self, path):
        """(cle de serie, nom a chercher sur AniList, [(numero, nature,
        termine)]) pour le suivi AniList, ou None. Un one-shot (tome sans
        numero, seul de sa serie) est decrit par un unique (None, ONESHOT,
        termine) : il n'est publie que si l'oeuvre AniList est en un seul tome
        (voir anilist_track). Un tome detache, ou place a la main dans une
        serie sans numero, n'est jamais publie : on ignore quel tome c'est."""
        def finished(p):
            prog = self.store.get_progress(p)
            return bool(prog and prog[2])

        e = self._entry_by_path.get(path)
        if e is None:   # fichier ouvert hors bibliotheque (double-clic)
            name, number, kind = parse_path(path)
            if number is None:
                kind = ONESHOT
            return (normalize_name(name), metadata.fold_accents(name),
                    [(number, kind, finished(path))])
        if e.detached:
            return None
        key = normalize_name(e.series)
        grp = self._group_entries(self._entries).get(key) or [e]
        if e.volume is None:
            if e.manual or len(grp) != 1:
                return None
            return key, metadata.fold_accents(e.series), [(None, ONESHOT, finished(path))]
        name = self._series_raw_name.get(key, e.series)
        # nature retenue pour la serie (un numero nu peut y etre un chapitre) ;
        # un tome virtuel n'est pas publie : ses chapitres le sont deja
        return key, metadata.fold_accents(name), [
            (x.volume, units.label_kind(x.kind, self._unit(x)), finished(x.path)) for x in grp
            if not virtual.is_virtual(x.path)]

    def _associate_anilist(self, key, path):
        """Association manuelle d'une serie a une oeuvre AniList (adresse de sa
        page ou numero), verifiee aupres d'AniList avant d'etre retenue."""
        if self.tracker is None:
            return
        name = self._series_display_name.get(key, key)
        text = prompt.ask_text(
            self, tr("Associer à AniList"),
            tr("Adresse de la page AniList de « {name} »\n"
               "(par exemple https://anilist.co/manga/30002/Berserk) ou son numéro :",
               name=name),
            validate=lambda t: (tr("Adresse non reconnue : copiez l'adresse d'une page "
                                   "« anilist.co/manga/… ».")
                                if t.strip() and anilist.parse_media_ref(t) is None else ""),
            ok_label=tr("Associer"))
        if text is None or not text.strip():
            return
        media_id = anilist.parse_media_ref(text)
        token = self.store.anilist_token()
        if not token:
            QMessageBox.warning(self, tr("Associer à AniList"),
                                tr("Reconnectez votre compte AniList dans les préférences."))
            return
        # verification hors du thread UI : l'interface ne gele pas pendant la
        # requete (une seconde instance, lancee pendant ce temps, attend une
        # reponse de celle-ci)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        call = CallWorker(lambda: anilist.media_entry(token, media_id))
        call.signals.done.connect(
            lambda media, err: self._on_anilist_media(key, path, media_id, media, err))
        self._anilist_call = call   # garde une reference (sinon GC)
        QThreadPool.globalInstance().start(call)

    def _on_anilist_media(self, key, path, media_id, media, err):
        self._anilist_call = None
        QApplication.restoreOverrideCursor()
        if media is None:
            error = (str(err) if err is not None
                     else tr("Aucune œuvre manga ne porte ce numéro sur AniList."))
            QMessageBox.warning(self, tr("Associer à AniList"), plain(error))
            return
        self.tracker.associate(key, media_id, media.get("title"))
        self.tracker.resync_series(key, path)
        self._update_detail()

    # ----- statistiques -----
    def _stats_holdings(self, key):
        """Instantane de la serie `key` pour ses statistiques (voir
        series_stats.SeriesHoldings) : son parcours de lecture dans l'ordre,
        tomes virtuels compris (avec leurs chapitres), sans les chapitres
        deja contenus dans un tome. None si ce n'est pas une serie de la
        bibliotheque."""
        grp = self._group_entries(self._entries).get(key)
        if not grp or len(grp) < 2:
            return None
        vols = sorted(grp, key=self._volume_sort_key)
        infos = {e.path: self._info.get(e.path) or self._entry_info(e) for e in vols}
        name = self._series_display_name.get(key, grp[0].series)
        author = (aggregate_series_info(name, list(infos.values())).author
                  or self._series_author(vols))
        items, extra = [], []
        for e in vols:
            info = infos[e.path]
            if e.path in self._grouped_chapters or self._unit(e) == units.COVERED:
                extra.append(info.key)      # lu avec son tome, hors du parcours
                continue
            members = self._virtual_members.get(e.path) or []
            prog = self.store.get_progress(e.path)
            total = (prog[1] if prog and prog[1] else None) or self.store.page_count(e.path) or 0
            items.append(series_stats.SeriesItem(
                e.volume, self._unit(e) or units.VOLUME, info.key, info.status,
                prog[0] if prog else 0, total, self._display_title(e),
                aliases=tuple(self.store.key_for(m.path) for m in members),
                covers=tuple(m.volume for m in members if m.volume is not None)))
        return series_stats.SeriesHoldings(key, name, author,
                                           tuple(sorted(items, key=series_stats.item_order)),
                                           tuple(extra))

    def _series_owner(self):
        """Cle de serie actuelle d'un tome de la bibliotheque (son empreinte
        pour un tome isole), None pour un tome absent : voir
        series_stats.collect_rows."""
        owners = {}
        for e in self._entries:
            info = self._info.get(e.path)
            if info is not None:
                owners[info.key] = info.series_key or info.key
        return owners.get

    def _series_seconds(self, key):
        """Temps passe dans la serie (panneau d'informations), 0 sans lecture."""
        holdings = self._stats_holdings(key)
        if holdings is None:
            return 0.0
        return series_stats.series_seconds(self.store.reading_log, holdings, self._series_owner())

    def open_series_stats(self, key):
        self.open_stats(series=key)

    def open_stats(self, series=None):
        # etat de la bibliotheque : tomes par statut, et pages qu'il reste a
        # lire dans les tomes non termines (pour le temps restant a lire)
        library = {"unread": 0, "reading": 0, "finished": 0,
                   "remaining_pages": 0, "unknown_pages": 0,
                   "remaining_by_volume": {}}
        resolve = {}   # empreinte -> (cle de serie, nom affiche), regroupements actuels
        titles = {}   # empreinte -> titre actuel du tome
        for e in self._entries:
            info = self._info.get(e.path) or self._entry_info(e)
            library[info.status] = library.get(info.status, 0) + 1
            titles[info.key] = info.title
            if info.series_key:
                resolve[info.key] = (info.series_key,
                                     self._series_display_name.get(info.series_key, e.series))
            else:
                resolve[info.key] = (info.key, info.title)
            if info.status == FINISHED:
                continue
            prog = self.store.get_progress(e.path)
            total = (prog[1] if prog and prog[1] else None) or self.store.page_count(e.path)
            if total:
                left = max(0, total - (prog[0] if prog else 0))
                library["remaining_pages"] += left
                by_volume = library["remaining_by_volume"]
                by_volume[info.key] = by_volume.get(info.key, 0) + left
            else:
                library["unknown_pages"] += 1
        dlg = StatsDialog(self.store, library, self.store.ui_pref("theme", "dark"), self,
                          resolve=resolve.get, titles=titles, holdings=self._stats_holdings,
                          open_series=self._enter_series, series=series)
        dlg.exec()

    # ----- mises a jour (facultatif) -----
    def check_updates(self, force=False, report=None):
        """Verifie si une version plus recente est publiee : une fois par jour
        au plus si l'option est activee, ou tout de suite (`force`,
        « Verifier maintenant »). `report(texte)` recoit le resultat en clair."""
        if not force:
            if not self.store.ui_pref("check_updates", False):
                return
            last = float(self.store.ui_pref("update_checked", 0) or 0)
            if time.time() - last < updates.CHECK_INTERVAL:
                return
        if getattr(self, "_update_call", None) is not None:
            return
        call = CallWorker(updates.latest_release)
        call.signals.done.connect(lambda result, err: self._on_update_checked(
            result, err, force, report))
        self._update_call = call
        QThreadPool.globalInstance().start(call)

    def _on_update_checked(self, release, err, force, report):
        self._update_call = None
        if err is not None:
            if report:
                report(tr("Vérification impossible : {error}", error=err))
            return
        self.store.set_ui_pref("update_checked", time.time())
        newer = updates.is_newer(release["version"])
        if newer and (force or self.store.ui_pref("update_dismissed") != release["version"]):
            self.show_update(release)
        if report:
            report(tr("Beheread {version} est disponible.", version=release["version"]) if newer
                   else tr("Beheread est à jour."))

    # ----- sauvegarde -----
    def _export_backup(self) -> str:
        default = Path.home() / f"beheread-sauvegarde-{time.strftime('%Y-%m-%d')}.json"
        path, _ = QFileDialog.getSaveFileName(self, tr("Exporter la progression"), str(default),
                                              tr("Sauvegarde Beheread (*.json)"))
        if not path:
            return ""
        try:
            self.store.export_backup(path)
        except OSError as e:
            QMessageBox.warning(self, tr("Export impossible"), plain(e))
            return ""
        return tr("Sauvegarde exportée : {path}", path=path)

    def _export_reading_csv(self) -> str:
        default = Path.home() / f"beheread-journal-{time.strftime('%Y-%m-%d')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, tr("Exporter le journal de lecture"),
                                              str(default), tr("Tableur CSV (*.csv)"))
        if not path:
            return ""
        try:
            n = self.store.export_reading_csv(path)
        except OSError as e:
            QMessageBox.warning(self, tr("Export impossible"), plain(e))
            return ""
        return trn(n, "Journal exporté ({n} ligne) : {path}",
                   "Journal exporté ({n} lignes) : {path}", path=path)

    def _import_backup(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self, tr("Importer une sauvegarde"), str(Path.home()),
                                              tr("Sauvegarde Beheread (*.json)"))
        if not path:
            return ""
        try:
            result = self.store.import_backup(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, tr("Import impossible"), plain(e))
            return ""
        self.refresh()   # les regroupements importes peuvent changer les series
        return tr("Import terminé : {progress} progression(s) et {extras} réglage(s) repris.",
                  progress=result["progress"], extras=result["extras"])
