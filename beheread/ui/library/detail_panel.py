"""Panneau d'informations de l'element selectionne.

Mixin de LibraryWidget : ces methodes partagent l'etat du widget
(self.list, self.store, self._entries...) ; elles sont regroupees ici par
responsabilite pour garder chaque fichier lisible."""

import os
import time

from PySide6.QtGui import QPixmap

from beheread.core.library_model import (
    FINISHED,
    READING,
    STATUS_LABELS,
    aggregate_series_info,
)
from beheread.core.series import normalize_name

# modules extraits (voir chacun) : constantes de rendu, delegates, dialogues et
# taches d'arriere-plan. LibraryWidget (ci-dessous) orchestre le tout.
from beheread.ui.library.constants import (
    ROLE_IS_SERIES,
    ROLE_PATH,
    ROLE_SERIES_KEY,
    ROLE_SERIES_PATHS,
)
from beheread.ui.library.detail import breakable


class DetailPanelMixin:
    # ----- panneau d'informations -----
    def _set_details_visible(self, visible):
        """Affiche ou masque le panneau (reglage des preferences)."""
        self._show_details = visible
        self.detail.setVisible(visible)
        self._update_detail()

    def _refresh_detail_for(self, path):
        """Met a jour le panneau si l'element courant concerne ce tome."""
        item = self.list.currentItem()
        if item is None or not self._show_details:
            return
        if item.data(ROLE_PATH) == path or path in (item.data(ROLE_SERIES_PATHS) or ()):
            self._update_detail()

    def _update_detail(self):
        if not self._show_details:
            return
        item = self.list.currentItem()
        if item is None or self.list.isRowHidden(self.list.row(item)):
            self.detail.clear()
        elif item.data(ROLE_IS_SERIES):
            self._show_series_detail(item.data(ROLE_SERIES_KEY))
        else:
            self._show_volume_detail(item.data(ROLE_PATH))

    def _cover_for_detail(self, path):
        pm = QPixmap(str(self.store.thumb_path(path)))   # cache disque, pleine resolution
        return pm if not pm.isNull() else self.covers.get(path)

    @staticmethod
    def _fmt_date(ts):
        return time.strftime("%d/%m/%Y", time.localtime(ts)) if ts else ""

    _SOURCE_LABELS = {"comicinfo": "ComicInfo.xml", "googlebooks": "Google Books",
                      "anilist": "AniList", "mangadex": "MangaDex",
                      "manual": "Saisie manuelle", "series": "Série"}

    def _show_volume_detail(self, path):
        e = self._entry_by_path.get(path)
        if e is None:
            self.detail.clear()
            return
        info = self._info.get(path) or self._entry_info(e)
        meta = self.store.volume_meta(path)
        meta = None if (meta and meta.get("not_found")) else meta
        prog = self.store.get_progress(path)
        status = info.status

        subtitle = ""
        if not e.detached and normalize_name(e.series) != normalize_name(e.title):
            subtitle = self._series_display_name.get(info.series_key, e.series)
            if e.volume is not None:
                subtitle += f"  ·  Tome {e.volume}"
        progress = STATUS_LABELS[status]
        if prog and prog[1] and status == READING:
            progress += f" — page {prog[0] + 1} / {prog[1]}"
        total = (prog[1] if prog and prog[1] else None) or self.store.page_count(path)
        estimate = self._time_estimate_text(path)
        try:
            size = f"{os.path.getsize(path) / 1_048_576:.1f} Mo".replace(".", ",")
        except OSError:
            size = ""
        rows = [
            ("Auteur", info.author),
            ("Année", str(info.year) if info.year else ""),
            ("Source", self._SOURCE_LABELS.get((meta or {}).get("source"), "")),
            ("Statut", progress),
            ("Pages", str(total) if total else ""),
            ("Durée", estimate.split(" : ", 1)[-1] if estimate else ""),
            ("Ajouté le", self._fmt_date(info.added)),
            ("Lu le", self._fmt_date(info.last_read)),
            ("Taille", size),
            # le chemin peut revenir a la ligne au lieu d'elargir le panneau
            ("Fichier", breakable(path)),
        ]
        primary = {READING: "Reprendre la lecture", FINISHED: "Relire"}.get(status, "Lire")
        actions = [(primary, lambda: self.mangaActivated.emit(path), True)]
        if status == FINISHED:
            actions.append(("Marquer comme non lu",
                            lambda: (self._mark_unread(path), self._rebuild_list()), False))
        else:
            actions.append(("Marquer comme lu",
                            lambda: (self._mark_finished(path), self._rebuild_list()), False))
        actions += [
            ("Modifier les informations…", lambda: self._edit_volume_info(path), False),
            ("Déplacer vers une série…", lambda: self._move_to_series([path]), False),
            ("Afficher dans l'explorateur", lambda: self._show_in_explorer(path), False),
        ]
        if info.series_key and not e.detached:
            self._add_anilist_detail(info.series_key, path, rows, actions)
        self.detail.show_content(self._cover_for_detail(path), e.title, subtitle,
                                 rows, actions)

    def _show_series_detail(self, key):
        grp = self._group_entries(self._entries).get(key)
        if not grp:
            self.detail.clear()
            return
        vols = sorted(grp, key=self._volume_sort_key)
        featured = vols[self._series_featured_index(vols)]
        name = self._series_display_name.get(key, grp[0].series)
        infos = [self._info.get(v.path) or self._entry_info(v) for v in vols]
        agg = aggregate_series_info(name, infos)
        read = sum(1 for i in infos if i.status == FINISHED)
        started = any(i.status != "unread" for i in infos)
        rows = [
            ("Auteur", agg.author or self._series_author(vols)),
            ("Année", str(agg.year) if agg.year else ""),
            ("Statut", STATUS_LABELS[agg.status]),
            ("Ajoutée le", self._fmt_date(agg.added)),
            ("Lue le", self._fmt_date(agg.last_read)),
        ]
        fpath = featured.path
        label = "Continuer" if started else "Commencer"
        if featured.volume is not None:
            # libelle court et propre plutot que le nom de fichier complet
            unit = "le chapitre" if featured.kind == "chapter" else "le tome"
            label = f"{label} {unit} {featured.volume}"
        else:
            label = f"{label} : {featured.title}"
        actions = [(label, lambda: self.mangaActivated.emit(fpath), True),
                   ("Ouvrir la série", lambda: self._enter_series(key), False)]
        if agg.status != FINISHED:
            actions.append(("Marquer la série comme lue",
                            lambda: self._mark_series_finished(key), False))
        actions += [
            ("Modifier les informations…", lambda: self._edit_series_info(key), False),
            ("Renommer la série…", lambda: self._rename_series(key), False),
            ("Fusionner avec une autre série…", lambda: self._merge_series(key), False),
        ]
        self._add_anilist_detail(key, fpath, rows, actions)
        self.detail.show_content(self._cover_for_detail(fpath), name,
                                 f"{len(vols)} tomes  ·  {read} lu" + ("s" if read > 1 else ""),
                                 rows, actions)

    def _add_anilist_detail(self, key, path, rows, actions):
        """Ligne « AniList » et actions d'association du panneau d'informations
        (seulement si un compte AniList est connecte)."""
        if self.tracker is None or not self.tracker.connected():
            return
        text, mapping = self.tracker.series_state(key)
        rows.append(("AniList", text))
        actions.append(("Associer à AniList…", lambda: self._associate_anilist(key, path), False))
        if mapping.get("ignored"):
            actions.append(("Suivre sur AniList",
                            lambda: (self.tracker.associate(key), self.tracker.resync_series(key, path)),
                            False))
        else:
            actions.append(("Ne pas suivre sur AniList",
                            lambda: self.tracker.associate(key, ignore=True), False))
