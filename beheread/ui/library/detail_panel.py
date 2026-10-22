"""Panneau d'informations de l'element selectionne.

Mixin de LibraryWidget : ces methodes partagent l'etat du widget
(self.list, self.store, self._entries...) ; elles sont regroupees ici par
responsabilite pour garder chaque fichier lisible."""

import os
import time

from PySide6.QtGui import QPixmap

from beheread import platforms
from beheread.core import units
from beheread.core.library_model import (
    FINISHED,
    READING,
    STATUS_LABELS,
    aggregate_series_info,
    describe_numbers,
    owned_numbers,
)
from beheread.core.series import normalize_name
from beheread.i18n import N_, fmt_decimal, tr, trn
from beheread.infra import servers as remote
from beheread.infra import virtual

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
        return time.strftime(tr("%d/%m/%Y"), time.localtime(ts)) if ts else ""

    # libelles traduits a l'affichage (tr)
    _SOURCE_LABELS = {"comicinfo": "ComicInfo.xml", "googlebooks": "Google Books",
                      "anilist": "AniList", "mangadex": "MangaDex", "bnf": "BnF",
                      "wikidata": "Wikidata", "isbn": "ISBN", "epub": "EPUB",
                      "seriesjson": "series.json",
                      "manual": N_("Saisie manuelle"), "series": N_("Série"),
                      "server": N_("Serveur")}

    def _server_name(self, path) -> str:
        """Nom du serveur d'un tome distant, "" pour un tome local."""
        if not self._is_remote(path) or self.servers is None:
            return ""
        config = self.servers.config(remote.split_path(path)[0])
        return config.name if config is not None else tr("Serveur")

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

        # le titre affiche porte deja serie et numero (« Berserk · Tome 1 ») ;
        # seul un tome sans numero range dans une serie la rappelle
        subtitle = ""
        if (not e.detached and e.volume is None
                and normalize_name(e.series) != normalize_name(e.title)):
            subtitle = self._series_display_name.get(info.series_key, e.series)
        progress = tr(STATUS_LABELS[status])
        if prog and prog[1] and status == READING:
            progress += " — " + tr("page {page} / {total}", page=prog[0] + 1, total=prog[1])
        total = (prog[1] if prog and prog[1] else None) or self.store.page_count(path)
        estimate = self._time_estimate_text(path)
        server = self._server_name(path)
        try:
            size = "" if server else f"{fmt_decimal(os.path.getsize(path) / 1_048_576)} {tr('Mo')}"
        except OSError:
            size = ""
        source = tr(self._SOURCE_LABELS.get((meta or {}).get("source"), ""))
        byline = " · ".join(p for p in (info.author, str(info.year) if info.year else "") if p)
        subtitle = "\n".join(p for p in (subtitle, byline) if p)
        rows = [
            (tr("Statut"), progress),
            (tr("Pages"), str(total) if total else ""),
            (tr("Série"), self._series_counts_text(info.series_key) if info.series_key else ""),
            (tr("Source"), server or source),
            (tr("Durée"), estimate.split(" : ", 1)[-1] if estimate else ""),
            (tr("Ajouté le"), self._fmt_date(info.added)),
            (tr("Lu le"), self._fmt_date(info.last_read)),
            (tr("Taille"), size),
            # le chemin peut revenir a la ligne au lieu d'elargir le panneau
            (tr("Fichier"), breakable(path)) if not server else (tr("Serveur"), server),
        ]
        is_virtual = virtual.is_virtual(path)
        if is_virtual:   # pas de fichier : ses chapitres
            rows[-1] = (tr("Chapitres"),
                        self._members_text(self._virtual_members.get(path) or []))
        primary = {READING: tr("Reprendre la lecture"), FINISHED: tr("Relire")}.get(status, tr("Lire"))
        actions = [(primary, lambda: self.mangaActivated.emit(path), True)]
        if status == FINISHED:
            actions.append((tr("Marquer comme non lu"),
                            lambda: (self._mark_unread(path), self._rebuild_list()), False))
        else:
            actions.append((tr("Marquer comme lu"),
                            lambda: (self._mark_finished(path), self._rebuild_list()), False))
        if is_virtual:
            actions += [
                (tr("Ajouter ou retirer des chapitres…"),
                 lambda: self._edit_virtual_chapters(path), False),
                (tr("Dissocier (garder les chapitres)"),
                 lambda: self._dissolve_virtual(path), False),
            ]
        else:
            actions += [
                (tr("Modifier les informations…"), lambda: self._edit_volume_info(path), False),
                (tr("Déplacer vers une série…"), lambda: self._move_to_series([path]), False),
            ]
        if not server and not is_virtual:
            actions.append((tr(platforms.REVEAL_LABEL), lambda: self._show_in_explorer(path), False))
        if info.series_key and not e.detached:
            self._add_anilist_detail(info.series_key, path, rows, actions)
        genres, summary = self._work_details(meta, info.series_key)
        self.detail.show_content(self._cover_for_detail(path), info.title, subtitle,
                                 rows, actions, self._metadata_notice(e), genres, summary)

    def _work_details(self, meta, series_key):
        """(genres, resume) de l'oeuvre : ceux de la serie, sinon du tome."""
        series = self.store.series_meta(series_key) if series_key else None
        for m in (series, meta):
            if m and not m.get("not_found") and (m.get("genres") or m.get("description")):
                return list(m.get("genres") or []), m.get("description") or ""
        return [], ""

    def _series_counts_text(self, key):
        """« 41 tomes parus · 38 possédés » (ou « 38 tomes possédés » si le
        nombre de tomes parus est inconnu), suivi des chapitres qui
        completent les tomes (« · 22 chapitres »)."""
        grp = self._group_entries(self._entries).get(key) or []
        if len(grp) < 2:
            return ""
        counts = self._series_counts(grp)
        chapters = (trn(counts.chapters, "{n} chapitre", "{n} chapitres")
                    if counts.chapters else "")
        if not counts.volumes:
            return chapters
        owned = len(owned_numbers(e.volume for e in grp if self._unit(e) == units.VOLUME))
        owned = owned or counts.volumes
        published = self._series_published(key)
        if published:
            text = (trn(published, "{n} tome paru", "{n} tomes parus") + " · "
                    + trn(owned, "{n} possédé", "{n} possédés"))
        else:
            text = tr("{n} tomes possédés", n=owned)
        return " · ".join(p for p in (text, chapters) if p)

    def _metadata_notice(self, e):
        """Avertissement du panneau quand la recherche d'auteur et d'annee de
        ce tome a echoue (services en ligne injoignables ou satures), avec le
        delai du prochain essai automatique et « Reessayer maintenant »."""
        failure = self.meta.failure(e.path)
        if failure is None:
            return None
        text = tr("Auteur et année introuvables pour l'instant : les services en ligne "
                  "ne répondent pas.")
        due = failure["due"]
        if due is not None:
            minutes = max(1, round(due / 60))
            text += " " + tr("Nouvel essai automatique dans {minutes} min.", minutes=minutes)

        def retry():
            self.meta.retry_now(e)
            self._update_detail()
        return text, tr("Réessayer maintenant"), retry

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
        started = any(i.status != "unread" for i in infos)
        author = agg.author or self._series_author(vols)
        byline = " · ".join(p for p in (author, str(agg.year) if agg.year else "") if p)
        _owned, missing, chapters, missing_ch, _published, _japan = self._series_holdings(key, vols)
        missing_text = describe_numbers(missing)
        if missing_ch:
            missing_text = " · ".join(p for p in (
                missing_text, tr("ch. {numbers}", numbers=describe_numbers(missing_ch))) if p)
        rows = [
            (tr("Contenu") if chapters else tr("Tomes"), self._series_counts_text(key)),
            (tr("Manquants"), missing_text),
            (tr("Lus"), units.progress_text(self._series_counts(vols))),
            (tr("Statut"), tr(STATUS_LABELS[agg.status])),
            (tr("Ajoutée le"), self._fmt_date(agg.added)),
            (tr("Lue le"), self._fmt_date(agg.last_read)),
        ]
        fpath = featured.path
        if featured.volume is not None:
            # libelle court et propre plutot que le nom de fichier complet
            if self._unit(featured) == units.CHAPTER:
                label = (tr("Continuer le chapitre {n}", n=featured.volume) if started
                         else tr("Commencer le chapitre {n}", n=featured.volume))
            else:
                label = (tr("Continuer le tome {n}", n=featured.volume) if started
                         else tr("Commencer le tome {n}", n=featured.volume))
        else:
            title = self._display_title(featured)
            label = (tr("Continuer : {title}", title=title) if started
                     else tr("Commencer : {title}", title=title))
        actions = [(label, lambda: self.mangaActivated.emit(fpath), True),
                   (tr("Ouvrir la série"), lambda: self._enter_series(key), False)]
        if agg.status != FINISHED:
            actions.append((tr("Marquer la série comme lue"),
                            lambda: self._mark_series_finished(key), False))
        actions += [
            (tr("Modifier les informations…"), lambda: self._edit_series_info(key), False),
            (tr("Renommer la série…"), lambda: self._rename_series(key), False),
            (tr("Fusionner avec une autre série…"), lambda: self._merge_series(key), False),
        ]
        self._add_anilist_detail(key, fpath, rows, actions)
        genres, summary = self._work_details(None, key)
        self.detail.show_content(self._cover_for_detail(fpath), name, byline,
                                 rows, actions, None, genres, summary)

    def _add_anilist_detail(self, key, path, rows, actions):
        """Ligne « AniList » et actions d'association du panneau d'informations
        (seulement si un compte AniList est connecte)."""
        if self.tracker is None or not self.tracker.connected():
            return
        text, mapping = self.tracker.series_state(key)
        rows.append(("AniList", text))
        actions.append((tr("Associer à AniList…"), lambda: self._associate_anilist(key, path), False))
        if mapping.get("ignored"):
            actions.append((tr("Suivre sur AniList"),
                            lambda: (self.tracker.associate(key), self.tracker.resync_series(key, path)),
                            False))
        else:
            actions.append((tr("Ne pas suivre sur AniList"),
                            lambda: self.tracker.associate(key, ignore=True), False))
