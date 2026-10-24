"""Series de la grille : unites (tomes, chapitres), dossiers de serie, leur
contenu a sections, leurs cases « Non possede », et l'entree / sortie d'un
dossier.

Mixin de LibraryWidget : ces methodes partagent l'etat du widget
(self.list, self.store, self._entries...) ; voir widget.py."""


from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QListWidgetItem,
)

from beheread.core import units
from beheread.core.library_model import (
    ALL,
    FINISHED,
    READING,
    aggregate_series_info,
    matches_status,
    missing_cells,
    missing_volumes,
    owned_numbers,
    sort_key,
    volume_status,
)
from beheread.core.series import (
    clean_title,
    edition_label,
    normalize_name,
    volume_hint,
    volume_label,
)
from beheread.i18n import N_, tr, trn
from beheread.infra import metadata, virtual
from beheread.ui import keys
from beheread.ui.library.constants import (
    ROLE_AUTHOR_TEXT,
    ROLE_FINISHED,
    ROLE_FRACTION,
    ROLE_IN_VOLUME,
    ROLE_IS_SERIES,
    ROLE_MISSING,
    ROLE_PATH,
    ROLE_PROG_TEXT,
    ROLE_SECTION,
    ROLE_SERIES_COUNT,
    ROLE_SERIES_KEY,
    ROLE_SERIES_PATHS,
    ROLE_SMALL,
    ROLE_VIRTUAL,
    SECTION_H,
)
from beheread.ui.safe_text import plain


class SeriesViewMixin:
    def _compute_units(self, entries):
        """Unite de chaque tome (tome relie, chapitre, cycle...), d'apres les
        natures des fichiers de sa serie et la nature de publication choisie
        par l'utilisateur (voir core/units.py)."""
        by_path = {}
        for key, grp in self._group_entries(entries).items():
            unit = units.classifier((e.kind for e in grp), self.store.series_nature(key))
            for e in grp:
                by_path[e.path] = (units.COVERED if e.path in self._grouped_chapters
                                   else unit(e.kind))
            self._mark_covered_chapters(key, grp, by_path)
            self._ensure_latest_releases(key, grp, by_path)
        for e in entries:
            if e.detached:
                by_path[e.path] = units.classifier([e.kind])(e.kind)
        return by_path

    def _mark_covered_chapters(self, key, grp, by_path):
        """Les chapitres deja contenus dans un tome possede (decoupage
        officiel, demande a MangaDex en arriere-plan) passent en
        units.COVERED - hors du parcours de lecture, masques par defaut. Le
        decoupage sert aussi a proposer un tome virtuel (serie en chapitres)."""
        chapters = [e for e in grp if by_path[e.path] == units.CHAPTER and e.volume is not None]
        if not chapters:
            return
        # tomes reels seulement : un tome virtuel cache deja ses chapitres
        volumes = [e.volume for e in grp if by_path[e.path] == units.VOLUME
                   and e.volume is not None and not virtual.is_virtual(e.path)]
        # decoupage qui ne connait pas le dernier tome possede : redemande
        # chaque jour (MangaDex se complete au fil des mises en ligne)
        known = self.store.chapter_ranges(key)
        incomplete = bool(volumes) and units.fmt_number(max(volumes)) not in known
        self.chapter_maps.ensure(key, self._series_raw_name.get(key, grp[0].series),
                                 incomplete=incomplete)
        if not volumes:
            return
        ranges = self._chapter_ranges(key)
        covered = units.covered_chapters([e.volume for e in chapters], volumes, ranges)
        for e in chapters:
            if e.volume in covered:
                by_path[e.path] = units.COVERED

    def _chapter_ranges(self, key):
        """Decoupage tomes/chapitres de la serie : MangaDex (et tomes arrives
        a la place d'un tome virtuel), complete par les noms de fichiers qui
        donnent le tome d'un chapitre (« Vol.22 Ch.199 », voir
        series.volume_hint) pour les tomes que MangaDex ne connait pas.
        Ces indices ne couvrent que les chapitres possedes : ils servent aux
        manquants et aux libelles, jamais a creer un tome virtuel."""
        cached = self._ranges_cache.get(key)
        if cached is not None:
            return cached
        ranges = dict(self.store.chapter_ranges(key))
        hints = {}
        for path in self._paths_by_series.get(key, ()):
            e = self._entry_by_path.get(path)
            if e is None or e.kind != "chapter" or e.volume is None:
                continue
            volume = volume_hint(e.title)
            if volume is not None:
                first, last = hints.get(volume, (e.volume, e.volume))
                hints[volume] = (min(first, e.volume), max(last, e.volume))
        for volume, (first, last) in hints.items():
            ranges.setdefault(str(volume), [first, last])
        self._ranges_cache[key] = ranges
        return ranges

    def _ensure_latest_releases(self, key, grp, by_path):
        """Serie en tomes seuls dont le nombre de tomes parus est inconnu
        (serie en cours : AniList ne le donne pas) : son dernier tome paru
        est demande a MangaDex (voir Store.latest_releases). Une serie qui a
        des chapitres l'obtient deja avec son decoupage."""
        if any(units.is_chapter(by_path[e.path]) for e in grp):
            return
        if not any(by_path[e.path] == units.VOLUME and e.volume is not None for e in grp):
            return
        if self._published_meta(key)[0] or self.store.series_published(key):
            return
        if self._series_edition(key):
            return   # MangaDex suit l'edition courante, pas celle-ci
        self.chapter_maps.ensure(key, self._series_raw_name.get(key, grp[0].series))

    def _on_chapter_map(self, key):
        """Decoupage ou dernieres parutions d'une serie arrives : la grille
        n'est reconstruite que si cela peut changer ce qu'elle montre (serie
        ouverte, ou serie avec chapitres dont la pile compte les chapitres
        deja dans un tome)."""
        paths = self._paths_by_series.get(key, ())
        if key == self._current_series or any(
                units.is_chapter(self._unit_by_path.get(p)) for p in paths):
            self._rebuild_list()

    def _unit(self, e):
        unit = self._unit_by_path.get(e.path, False)
        return units.classifier([e.kind])(e.kind) if unit is False else unit

    def _group_entries(self, entries):
        """Regroupe les tomes par cle de serie normalisee. Les tomes detaches
        manuellement (clic droit) sont exclus du regroupement : ils restent
        des tomes isoles."""
        groups = {}
        for e in entries:
            if e.detached:
                continue
            groups.setdefault(normalize_name(e.series), []).append(e)
        return groups

    def _rebuild_series_folders(self, entries):
        """Niveau racine du mode regroupe : un dossier par serie multi-tomes,
        les series a un seul tome (et les tomes detaches) affichees comme un
        tome normal. Series et tomes isoles sont intercales par ordre
        alphabetique."""
        groups = self._group_entries(entries)
        renderables = []   # (cle de tri, "item"|"series", charge utile)
        wanted = self._status_filter

        def add_single(e):
            info = self._info[e.path]
            if matches_status(info.status, wanted):
                renderables.append((sort_key(self._sort, info), "item", e))

        for key, grp in groups.items():
            if len(grp) == 1:
                add_single(grp[0])
            else:
                name = self._series_display_name.get(key, grp[0].series)
                agg = aggregate_series_info(name, (self._info[e.path] for e in grp))
                if matches_status(agg.status, wanted):
                    renderables.append((sort_key(self._sort, agg), "series", (key, grp)))
        for e in entries:
            if e.detached:
                add_single(e)
        for _, kind, payload in sorted(renderables, key=lambda r: r[0]):
            if kind == "item":
                self._add_item(payload)
            else:
                self._add_series_item(*payload)

    def _rebuild_series_contents(self, entries):
        """Contenu d'un dossier de serie ouvert : son bandeau (tomes et
        chapitres possedes, manquants), puis ses tomes tries par numero et les
        chapitres qui les completent, les manquants intercales a leur place si
        on le demande."""
        key = self._current_series
        grp = self._group_entries(entries).get(key)
        if not grp:
            # la serie a disparu (fichiers retires) : on remonte au niveau racine
            self._current_series = None
            self._rebuild_series_folders(entries)
            return
        vols = sorted(grp, key=self._volume_sort_key)
        name = self._series_display_name.get(key, grp[0].series)
        owned, missing, chapters, missing_ch, published, japan = self._series_holdings(key, vols)
        show_missing = bool(self.store.library_pref("show_missing", True))
        sub = [self._series_author(vols) or self._series_author_text(key),
               self._series_edition(key)]
        if published and self.store.series_published(key):
            sub.append(trn(published, "{n} tome paru", "{n} tomes parus"))   # saisi a la main
        elif published:
            source = tr(self._SOURCE_LABELS.get(self._published_meta(key)[1], ""))
            sub.append(trn(published, "{n} tome paru ({source})", "{n} tomes parus ({source})",
                           source=source) if source
                       else trn(published, "{n} tome paru", "{n} tomes parus"))
        n_volumes = sum(1 for e in vols if not units.is_chapter(self._unit(e)))
        show_covered = bool(self.store.library_pref("show_covered_chapters", False))
        # tomes affiches : reels et virtuels (les manquants, eux, ne comptent
        # que les reels, voir _series_holdings)
        shown_volumes = len(owned_numbers(e.volume for e in vols if self._unit(e) == units.VOLUME))
        self.series_band.set_content(
            name, " · ".join(p for p in sub if p), shown_volumes or n_volumes, published,
            chapters=len(chapters),
            chapter_range=(units.chapter_range_text(min(chapters), max(chapters))
                           if chapters and n_volumes else ""))
        self.series_band.show()

        # dans une serie, l'ordre des tomes reste l'ordre de lecture : les
        # tomes par numero, puis - section a part, en petites cases en vue
        # grille - les chapitres qui les completent
        wanted = self._status_filter
        # chapitres d'un tome virtuel : jamais ici (on les lit en ouvrant ce
        # tome) ; ceux deja dans un tome possede : seulement sur demande
        shown = [e for e in vols if matches_status(self._info[e.path].status, wanted)
                 and e.path not in self._grouped_chapters
                 and (show_covered or self._unit(e) != units.COVERED)]
        volume_part = [e for e in shown if not units.is_chapter(self._unit(e))]
        chapter_part = [e for e in shown if units.is_chapter(self._unit(e))]
        # tous les chapitres sont deja dans des tomes (officiels ou virtuels) :
        # pas de section « Suite en chapitres », meme quand on les affiche
        has_chapters = any(self._unit(e) == units.CHAPTER for e in vols)
        if not has_chapters:
            chapter_part = []
        self._want_sections = has_chapters
        cells = {units.VOLUME: [], units.CHAPTER: []}
        if show_missing and wanted == ALL:
            # (premier, dernier, paru au Japon seulement)
            cells = {units.VOLUME: [(*c, False) for c in missing_cells(missing)]
                     + [(*c, True) for c in missing_cells(japan)],
                     units.CHAPTER: [(*c, False) for c in missing_cells(missing_ch)]}
        both = n_volumes and has_chapters
        if both:
            self._add_section_item(tr("Tomes"), self._volumes_section_text(vols))
        self._add_series_part(volume_part, cells[units.VOLUME], name, units.VOLUME, False)
        if both:
            self._add_section_item(tr("Suite en chapitres"), self._chapters_section_text(vols))
        self._add_series_part(chapter_part, cells[units.CHAPTER], name, units.CHAPTER, True)

    def _add_series_part(self, entries, cells, series_name, unit, small):
        """Tomes (ou chapitres) d'un dossier de serie ouvert, les cases
        « non possede » intercalees a leur place."""
        cells = list(cells)
        for e in entries:
            while cells and e.volume is not None and cells[0][0] < e.volume:
                self._add_missing_item(cells.pop(0), series_name, unit, small)
            self._add_item(e, small=small)
        for cell in cells:
            self._add_missing_item(cell, series_name, unit, small)

    def _volumes_section_text(self, vols):
        """« 22 tomes · 6 lus »."""
        counts = self._series_counts([e for e in vols if not units.is_chapter(self._unit(e))])
        text = trn(counts.volumes, "{n} tome", "{n} tomes")
        if counts.volumes_read:
            text += " · " + trn(counts.volumes_read, "{n} lu", "{n} lus")
        return text

    def _chapters_section_text(self, vols):
        """« ch. 211 à 232 · 20 possédés · chapitre 213 en cours »."""
        counts = self._series_counts(vols)
        parts = []
        if counts.first_chapter is not None:
            parts.append(units.chapter_range_text(counts.first_chapter, counts.last_chapter))
        parts.append(trn(counts.chapters, "{n} possédé", "{n} possédés"))
        if counts.current_chapter is not None:
            parts.append(tr("chapitre {n} en cours", n=units.fmt_number(counts.current_chapter)))
        return " · ".join(parts)

    def _add_section_item(self, title, subtitle):
        """En-tete de section (« Tomes », « Suite en chapitres ») : toute la
        largeur de la grille (voir SmoothListWidget._fit_sections)."""
        item = QListWidgetItem(title)
        item.setData(ROLE_SECTION, (title, subtitle))
        item.setFlags(Qt.ItemIsEnabled)   # ni selection, ni ouverture
        item.setSizeHint(QSize(self.grid_delegate.cell_w, SECTION_H))
        self.list.addItem(item)
        self._row_paths.append(())
        self._row_visible.append(True)

    def _apply_sections(self):
        """Mise en page en flux pour un dossier de serie a sections, grille
        fixe sinon (voir _apply_grid_layout)."""
        if self._want_sections != self._sectioned:
            self._sectioned = self._want_sections
            if self._view_mode != "list":
                self._apply_grid_layout()
        self.list.fit_sections()

    def _series_holdings(self, key, vols):
        """(numeros de tomes possedes, tomes manquants, numeros de chapitres
        possedes, chapitres manquants, tomes parus ou None) d'une serie. Seuls
        des tomes relies se comptent comme tomes (pas les chapitres ni les
        cycles), et dans une serie qui a des chapitres, seuls les trous entre
        tomes possedes manquent. Dans une serie mixte, les chapitres manquants se comptent a
        partir de celui qui suit le dernier tome possede (decoupage officiel
        connu), sinon du premier possede : ceux d'avant sont dans les tomes.
        Les chapitres parus apres le dernier possede (MangaDex) manquent aussi.
        Dernier element : tomes parus au Japon apres le dernier possede, pour
        une serie en tomes seuls dont le nombre de tomes parus est inconnu
        (serie en cours, voir Store.latest_releases)."""
        # un tome virtuel porte un numero choisi par l'utilisateur : il ne
        # cree pas de « tome manquant » entre les tomes reels et lui
        owned = owned_numbers(e.volume for e in vols if self._unit(e) == units.VOLUME
                              and not virtual.is_virtual(e.path))
        published = self._series_published(key)
        chapters = [e.volume for e in vols
                    if self._unit(e) == units.CHAPTER and e.volume is not None]
        # possedes, pour les manquants : les chapitres masques comptent aussi
        held = [e.volume for e in vols
                if units.is_chapter(self._unit(e)) and e.volume is not None]
        start = None
        if not any(not units.is_chapter(self._unit(e)) for e in vols):
            start = 1
        else:
            real = owned_numbers(e.volume for e in vols if self._unit(e) == units.VOLUME
                                 and not virtual.is_virtual(e.path))
            end = units.coverage_end(real, self._chapter_ranges(key))
            if end is not None:
                start = int(end) + 1
        missing_ch = units.missing_chapters(held, start)
        last_volume, last_chapter = self.store.latest_releases(key)
        if held and last_chapter is not None and int(last_chapter) > max(held):
            # chapitres parus depuis le dernier possede (MangaDex)
            missing_ch += list(range(int(max(held)) + 1, int(last_chapter) + 1))
        # serie qui a des chapitres : ils prennent la suite des tomes, ceux
        # parus apres le dernier tome possede ne « manquent » pas
        missing = missing_volumes(owned, None if held else published)
        japan = []
        if (not held and published is None and owned and last_volume
                and not self._series_edition(key)):
            japan = list(range(max(owned) + 1, last_volume + 1))
        return owned, missing, chapters, missing_ch, published, japan

    def _series_edition(self, key):
        """Edition au decoupage different, ou "" : d'apres les noms de
        fichiers (« Perfect Edition », voir series.edition_label), sinon
        d'apres l'epaisseur des tomes (« Gros volumes (~530 pages) » : en
        moyenne plus de units.LARGE_VOLUME_PAGES pages, nombre connu des que
        la couverture a ete generee)."""
        pages = []
        for path in self._paths_by_series.get(key, ()):
            e = self._entry_by_path.get(path)
            if e is None or virtual.is_virtual(path):
                continue
            label = edition_label(e.title)
            if label:
                return label
            if e.kind in ("volume", "bare") and self.store.page_count(path):
                pages.append(self.store.page_count(path))
        if pages and sum(pages) / len(pages) > units.LARGE_VOLUME_PAGES:
            return tr("Gros volumes (~{n} pages)", n=int(round(sum(pages) / len(pages), -1)))
        return ""

    def _series_published(self, key):
        """Nombre de tomes parus de la serie (base en ligne), ou None. Un
        nombre inferieur au plus grand tome possede est ecarte : il est faux
        pour cette edition (oeuvre parue en un volume au Japon, decoupee en
        trois en France ; fiche de la mauvaise oeuvre). Les chapitres, qui
        vont au-dela des tomes parus, n'entrent pas dans la comparaison."""
        manual = self.store.series_published(key)
        if manual:
            return manual
        if self._series_edition(key):
            return None   # le nombre trouve en ligne est celui d'une autre edition
        volumes, _source = self._published_meta(key)
        if volumes is None:
            return None
        entries = (self._entry_by_path.get(p) for p in self._paths_by_series.get(key, ()))
        # un tome virtuel peut devancer les tomes parus : il n'entre pas en compte
        owned = owned_numbers(e.volume for e in entries
                              if e is not None and not e.detached
                              and self._unit(e) == units.VOLUME
                              and not virtual.is_virtual(e.path))
        return None if owned and max(owned) > volumes else volumes

    def _published_meta(self, key):
        """(nombre de tomes parus, source) d'apres les metadonnees, ou
        (None, None) : le plus grand nombre de tomes donne par les
        metadonnees locales des tomes (« Count » de ComicInfo.xml, series.json),
        comme Komga - celui de l'edition possedee -, sinon celui de la base en
        ligne de la serie."""
        local = []
        for path in self._paths_by_series.get(key, ()):
            meta = self.store.volume_meta(path) or {}
            count = meta.get("volumes")
            if meta.get("source") in metadata.LOCAL_SOURCES and isinstance(count, int)                     and count > 0:
                local.append((count, meta["source"]))
        if local:
            return max(local)
        sm = self.store.series_meta(key) or {}
        volumes = sm.get("volumes") if not sm.get("not_found") else None
        if isinstance(volumes, int) and volumes > 0:
            return volumes, sm.get("source")
        return None, None

    def _add_missing_item(self, cell, series_name, unit=units.VOLUME, small=False):
        """`cell` : (premier, dernier[, paru au Japon seulement])."""
        first, last, *rest = cell
        japan = bool(rest and rest[0])
        if unit == units.CHAPTER:
            label = (tr("Chapitre {n}", n=first) if first == last
                     else tr("Chapitres {first} à {last}", first=first, last=last))
        else:
            label = (tr("Tome {n}", n=first) if first == last
                     else tr("Tomes {first} à {last}", first=first, last=last))
        # petite case d'un chapitre : sans le nom de la serie, comme ses voisines
        item = QListWidgetItem(label if small else f"{series_name} · {label}")
        item.setData(ROLE_MISSING, (first, last, unit, japan))
        item.setData(ROLE_SMALL, small)
        item.setFlags(Qt.ItemIsEnabled)   # ni selection, ni ouverture
        item.setToolTip(plain(f"{series_name} · {label}\n"
                              + (tr("Paru au Japon, pas encore dans votre langue") if japan
                                 else tr("Non possédé"))))
        self.list.addItem(item)
        self._row_paths.append(())
        self._row_visible.append(True)

    def _volume_sort_key(self, e):
        """Ordre de lecture : tomes par numero, puis les chapitres."""
        return (units.order_key(self._unit(e), e.volume), e.title.casefold())

    def _display_title(self, e):
        """Titre affiche d'un tome : « Berserk · Tome 1 » plutot que le nom de
        fichier brut (« Berserk T01 (Miura) (2004) [Digital-1699] ... »),
        qui reste visible dans l'info-bulle et le panneau d'informations. Sans
        numero reconnu (one-shot, plage de tomes) : le nom de fichier, debarrasse
        des groupes de release. Un numero nu range parmi les chapitres
        s'affiche « Chapitre »."""
        if e.volume is None or e.kind == "range":
            return clean_title(e.title)
        name = e.series
        if not e.detached:
            name = self._series_display_name.get(normalize_name(e.series), e.series)
        return f"{name} · {volume_label(e.volume, units.label_kind(e.kind, self._unit(e)))}"

    def _add_item(self, e, small=False):
        """`small` : chapitre d'un dossier de serie ouvert, en petite case et
        sans le nom de la serie (« Chapitre 211 »)."""
        if small and e.volume is not None:
            title = volume_label(e.volume, units.label_kind(e.kind, self._unit(e)))
        else:
            title = self._display_title(e)
        item = QListWidgetItem(title)
        item.setData(ROLE_PATH, e.path)
        item.setData(ROLE_SMALL, small)
        item.setData(ROLE_VIRTUAL, virtual.is_virtual(e.path))
        if units.is_chapter(self._unit(e)):
            volume = units.volume_of(e.volume, self._chapter_ranges(normalize_name(e.series)))
            item.setData(ROLE_IN_VOLUME, tr("Tome {n}", n=volume) if volume else None)
        # declenche (ou reutilise) la recherche de metadonnees pour toute la
        # bibliotheque, pas seulement quand on trie par auteur/date : l'info
        # se remplit progressivement en arriere-plan des l'affichage, sans
        # reconstruire la liste a chaque reponse (voir _on_meta_done).
        meta = self._get_or_fetch_meta(e)
        tooltip, author_text = self._meta_tooltip_and_author(e.path, meta)
        item.setData(ROLE_AUTHOR_TEXT, author_text)
        item.setToolTip(plain(tooltip))
        self._apply_progress(item, e.path)
        self.list.addItem(item)
        self._row_paths.append((e.path,))
        self._row_visible.append(True)
        self._path_to_item[e.path] = item

    def _series_featured_index(self, vols):
        """Indice (dans `vols`, tries par numero) du tome a mettre en tete de
        pile d'un dossier de serie : le tome en cours de lecture (prioritaire),
        sinon celui qui suit le dernier tome termine - c'est le prochain a
        lire - ou le dernier termine lui-meme s'il clot la serie, sinon le
        premier tome."""
        in_progress = None
        last_finished = None
        for i, e in enumerate(vols):
            prog = self.store.get_progress(e.path)
            if not prog:
                continue
            if prog[2]:
                last_finished = i
            else:
                in_progress = i   # garde le plus avance (liste triee par numero)
        if in_progress is not None:
            return in_progress
        if last_finished is not None:
            return min(last_finished + 1, len(vols) - 1)
        return 0

    def _series_author(self, vols):
        """Auteur(s) connus pour la serie : premiere metadonnee en cache parmi
        ses tomes (aucune recherche declenchee ici)."""
        for e in vols:
            meta = self.store.volume_meta(e.path)
            if meta and not meta.get("not_found") and meta.get("authors"):
                return ", ".join(meta["authors"])
        return ""

    def _add_series_item(self, key, group):
        # les chapitres deja contenus dans un tome possede ne comptent pas
        group = [e for e in group if self._unit(e) != units.COVERED] or group
        display = self._series_display_name.get(key, group[0].series)
        item = QListWidgetItem(display)
        item.setData(ROLE_IS_SERIES, True)
        item.setData(ROLE_SERIES_KEY, key)
        item.setData(ROLE_SERIES_COUNT, len(group))

        # tete de pile : le tome pertinent (en cours / prochain a lire), les
        # couches arriere montrant les tomes qui le suivent
        vols = sorted(group, key=self._volume_sort_key)
        f = self._series_featured_index(vols)
        rotated = vols[f:] + vols[:f]
        cover_paths = [v.path for v in rotated[:3]]
        item.setData(ROLE_SERIES_PATHS, cover_paths)

        counts = self._series_counts(group)
        item.setData(ROLE_FRACTION, counts.read / counts.total if counts.total else 0.0)
        item.setData(ROLE_FINISHED, counts.total > 0 and counts.read == counts.total)
        item.setData(ROLE_PROG_TEXT, units.progress_text(counts))

        # auteur : depuis le cache des tomes ; la recherche est declenchee pour
        # le tome vedette et l'item s'abonne au resultat (voir _update_item_meta)
        self._get_or_fetch_meta(rotated[0])
        author = self._series_author(vols)
        item.setData(ROLE_AUTHOR_TEXT, author)
        self._meta_subscribers.setdefault(rotated[0].path, []).append(item)

        tooltip = f"{display}  ·  " + units.count_text(counts.volumes, counts.chapters)
        if author:
            tooltip += "\n" + tr("Auteur : {author}", author=author)
        item.setToolTip(plain(tooltip))

        self.list.addItem(item)
        self._row_paths.append(tuple(e.path for e in group))
        self._row_visible.append(True)

    def _series_counts(self, group):
        """Contenu et avancement d'une serie, tomes et chapitres a part (voir
        units.SeriesCounts)."""
        def item(e):
            status = volume_status(self.store.get_progress(e.path))
            return (self._unit(e), e.volume, status == FINISHED, status == READING)
        return units.series_counts(item(e) for e in group)

    # ----- navigation dans les dossiers de serie -----
    def _enter_series(self, key):
        # memorise la position a la racine pour y revenir en sortant
        self._root_position = (self.list_host.position(), ("series", key))
        self._current_series = key
        self._rebuild_list(keep_position=False)
        self.list_host.set_position(0)
        self.list.setFocus()

    def _exit_series(self):
        if self._current_series is None:
            return
        self._current_series = None
        self._rebuild_list(keep_position=False)
        pos, current = self._root_position
        self.list.doItemsLayout()
        self._restore_current(current)
        self.list_host.set_position(pos)
        self.list.setFocus()

    def _go_home(self):
        """Clic sur le logo "BEHEREAD" : retour a la racine de la
        bibliotheque - quitte un dossier de serie ouvert et efface une
        recherche en cours, comme un logo de site ramene a l'accueil."""
        changed = self._current_series is not None or bool(self._search_text)
        self._current_series = None
        if self._search_text:
            self.search_edit.blockSignals(True)
            self.search_edit.clear()
            self.search_edit.blockSignals(False)
            self._search_text = ""
            self._pre_search_position = None
        if changed:
            self._rebuild_list(keep_position=False)
        self.list.setFocus()

    def _update_back_button(self):
        if self._current_series is not None:
            name = self._series_display_name.get(self._current_series, "Serie")
            # nom raccourci au besoin : un nom tres long elargirait les deux
            # cotes de l'en-tete (la recherche reste centree, voir _balance_header)
            self.btn_back.setText(self.btn_back.fontMetrics().elidedText(
                name, Qt.ElideRight, 220))
            self.btn_back.setToolTip(plain(f"{name}\n" + tr("Retour à la bibliothèque")
                                           + "   " + keys.label(N_("Échap"))))
            self.btn_back.show()
        else:
            self.btn_back.hide()
        self._balance_header()
