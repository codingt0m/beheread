"""Bibliotheque : grille (ou liste) de vignettes des mangas trouves dans les
dossiers sources, avec recherche, regroupement par serie (dossiers) et
actions (suppression, reinitialisation, marquage lu, renommage) sur simple ou
multiple selection. Les couvertures sont generees en arriere-plan et mises
en cache sur disque."""

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from beheread.config import THUMB_SCALE
from beheread.core.library_model import (
    ALL,
    SORT_KEYS,
    STATUS_FILTERS,
    aggregate_series_info,
    continue_reading,
    matches_status,
    sort_key,
    volume_status,
)
from beheread.core.models import LibraryEntry, VolumeInfo
from beheread.core.series import normalize_name, parse_series_ex
from beheread.infra.storage import Store, is_cloud_placeholder
from beheread.ui.help_overlay import LIBRARY_SHORTCUTS, ShortcutOverlay

# modules extraits (voir chacun) : constantes de rendu, delegates, dialogues et
# taches d'arriere-plan. LibraryWidget (ci-dessous) orchestre le tout.
from beheread.ui.library.actions import ActionsMixin
from beheread.ui.library.chrome import ChromeMixin
from beheread.ui.library.constants import (
    ROLE_AUTHOR_TEXT,
    ROLE_FINISHED,
    ROLE_FRACTION,
    ROLE_IS_SERIES,
    ROLE_PATH,
    ROLE_PIXMAP,
    ROLE_PIXMAP2,
    ROLE_PIXMAP3,
    ROLE_PROG_TEXT,
    ROLE_SERIES_COUNT,
    ROLE_SERIES_KEY,
    ROLE_SERIES_PATHS,
    THUMB_H,
    THUMB_W,
)
from beheread.ui.library.controllers import (
    CoverCache,
    MetadataController,
    ScanController,
)
from beheread.ui.library.delegates import ListDelegate, MangaDelegate
from beheread.ui.library.detail import DetailPanel
from beheread.ui.library.detail_panel import DetailPanelMixin
from beheread.ui.library.menus import MenusMixin
from beheread.ui.library.services import ServicesMixin
from beheread.ui.library.shelf import ContinueShelf
from beheread.ui.library.views import ScrollingHeaderHost, SmoothListWidget

# ---------------------------------------------------------------- widget

class LibraryWidget(ChromeMixin, DetailPanelMixin, ActionsMixin, MenusMixin,
                    ServicesMixin, QWidget):
    mangaActivated = Signal(str)
    themeToggleRequested = Signal()
    preferencesChanged = Signal()   # preferences modifiees (theme, raccourci global...)
    volumesFinished = Signal(list)  # tomes marques « lus » depuis la bibliotheque (suivi AniList)

    # bornes du curseur de taille des couvertures (pourcentage de la taille de
    # reference). Le maximum est cale sur la resolution du cache de vignettes
    # (THUMB_SCALE fois la taille de reference) pour rester net meme sur un
    # ecran haute densite : au-dela, on afficherait plus grand que le cache.
    GRID_SCALE_MIN = 60
    GRID_SCALE_MAX = 100 * THUMB_SCALE // 2   # 150% (cache 3x, ecran jusqu'a 2x)

    @classmethod
    def _clamp_scale(cls, pct: int) -> int:
        return max(cls.GRID_SCALE_MIN, min(cls.GRID_SCALE_MAX, pct))

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self._entries = []              # LibraryEntry (voir core/models.py)
        self._path_to_item = {}         # path -> QListWidgetItem (tome, acces O(1))
        # chemin -> dossiers de serie interesses par ses metadonnees (auteur)
        self._meta_subscribers = {}
        # serie ouverte (drill-in) : None au niveau racine, sinon cle de serie
        self._current_series = None
        self._series_display_name = {}   # cle normalisee -> nom affiche (vote)
        self._entry_by_path = {}         # path -> entree (acces O(1))

        self._search_text = ""
        self._group_series = bool(store.library_pref("group_series", False))
        self._view_mode = store.library_pref("view_mode", "grid")
        # taille des couvertures en vue grille (pourcentage, cf. curseur du
        # header et MangaDelegate.set_scale) ; borne haute alignee sur la
        # resolution du cache de vignettes pour rester net (voir GRID_SCALE_MAX)
        self._grid_scale_pct = self._clamp_scale(
            int(store.library_pref("grid_scale_pct", 100)))
        self._cover_size = self._cover_display_size()

        # controleurs (threads et etat propres, voir controllers.py)
        self.scanner = ScanController(store, self)
        self.scanner.scanStarted.connect(self._on_scan_started)
        self.scanner.scanned.connect(self._on_scanned)
        self.meta = MetadataController(store, self._online_meta, self)
        self.meta.volumeUpdated.connect(self._update_item_meta)
        self.meta.seriesUpdated.connect(self._on_series_meta_updated)
        self.covers = CoverCache(store, self._cover_size, self)
        self.covers.coverReady.connect(self._on_cover_ready)
        # tri et filtre de statut (barre d'outils), panneaux optionnels
        self._sort = store.library_pref("sort", "title")
        if self._sort not in SORT_KEYS:
            self._sort = "title"
        self._status_filter = store.library_pref("status_filter", ALL)
        if self._status_filter not in {k for k, _ in STATUS_FILTERS}:
            self._status_filter = ALL
        self._show_continue = bool(store.library_pref("show_continue", True))
        self._show_details = bool(store.library_pref("show_details", False))
        self._info = {}            # path -> info de tri/statut (library_model), par reconstruction
        self._series_raw_name = {}   # cle de serie -> nom issu des fichiers (vote)
        self._root_position = (0, None)   # defilement + element courant a la racine
        # service fourni par la fenetre principale (voir set_services)
        self.tracker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())
        QShortcut(QKeySequence("F5"), self, self.refresh)
        QShortcut(QKeySequence.Find, self, self.search_edit.setFocus)   # Ctrl+F
        QShortcut(QKeySequence(Qt.Key_F1), self, self._toggle_help)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._build_consent_banner())

        # corps : [bande « Continuer » + grille (ou etat vide)] | panneau d'infos
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        layout.addLayout(body, 1)
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        body.addLayout(content, 1)
        self.shelf = ContinueShelf(self.store)
        self.shelf.activated.connect(self.mangaActivated.emit)
        self.shelf.contextMenuRequested.connect(self._show_shelf_menu)
        self.shelf.hide()

        self.list = SmoothListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setWordWrap(True)
        # necessaire pour que le defilement au pixel de SmoothListWidget ne
        # soit pas re-aligne sur les cases par la vue
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setHorizontalScrollMode(QListWidget.ScrollPerPixel)
        self.list.itemActivated.connect(self._on_activated)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        self.list.setAccessibleName("Bibliothèque")
        # Suppr : limite a la liste (ne doit pas agir pendant une saisie de recherche)
        del_shortcut = QShortcut(QKeySequence.Delete, self.list, self._delete_selected)
        del_shortcut.setContext(Qt.WidgetShortcut)
        self.list.currentItemChanged.connect(lambda *_: self._update_detail())
        # la bande « Continuer » defile avec la grille au lieu de rester fixe
        self.list_host = ScrollingHeaderHost(self.shelf, self.list)
        content.addWidget(self.list_host, 1)

        self.grid_delegate = MangaDelegate(self.store, self.list)
        self.grid_delegate.set_scale(self._grid_scale_pct / 100.0)
        self.list_delegate = ListDelegate(self.store, self.list)
        self._apply_view_mode()

        content.addWidget(self._build_empty_panel(), 1)
        self.detail = DetailPanel()
        self.detail.setVisible(self._show_details)
        body.addWidget(self.detail)
        self._help = ShortcutOverlay(LIBRARY_SHORTCUTS, self, take_focus=True)

        # glisser-deposer : un dossier l'ajoute a la bibliotheque, un fichier
        # CBZ/CBR/EPUB/PDF s'ouvre dans le lecteur
        self.setAcceptDrops(True)

        self.apply_theme()

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._rebuild_list)

        self.list.backRequested.connect(self._exit_series)

        # offline-first : affiche l'instantane persiste immediatement, puis
        # lance le scan reel en arriere-plan pour reconcilier
        self._load_persisted_index()
        self.refresh()
        self.list.setFocus()


    def _dedupe_by_content(self, paths):
        """Deux fichiers identiques (meme contenu - copie du meme tome dans
        un autre dossier source, ou doublon au meme endroit) ne doivent
        apparaitre qu'une seule fois dans la bibliotheque. La progression,
        les metadonnees et la vignette sont deja partagees par empreinte de
        contenu (voir Store.key_for) : il suffit ici de ne garder qu'un seul
        chemin representant par empreinte, choisi de facon stable (ordre
        alphabetique) pour que ce ne soit jamais le meme fichier qui
        "disparaisse" arbitrairement d'un rafraichissement a l'autre."""
        kept_path_for_key = {}
        result = []
        for p in sorted(paths):
            key = self.store.key_for(p)
            if key not in kept_path_for_key:
                kept_path_for_key[key] = p
                result.append(p)
        return result

    def _dedupe_by_series_volume(self, entries):
        """Deux fichiers *differents* (releases distinctes, scans differents -
        pas detectes par _dedupe_by_content qui ne voit que le contenu
        identique) peuvent neanmoins etre le meme tome de la meme serie
        (ex. "Berserk Volume 42" et "Berserk_T42"). On ne garde alors qu'un
        seul representant par (serie normalisee, numero de tome), en
        privilegiant celui qui reflete le mieux la lecture en cours -
        termine, puis entame, puis a defaut le premier par ordre alphabetique
        (stable). Les tomes sans numero detectable (one-shots, titres
        isoles) ne sont jamais fusionnes entre eux : leur seule identite
        fiable est le nom de fichier exact."""
        groups = {}
        singles = []
        for e in entries:
            # sans numero, ou place a la main dans une serie (deplacement,
            # fusion) : jamais fusionne - un regroupement choisi par
            # l'utilisateur ne doit pas faire disparaitre de tome
            if e.volume is None or e.manual:
                singles.append(e)
                continue
            # la NATURE du numero fait partie de la cle : un chapitre et un tome
            # de meme numero (ou un numero nu, d'identite fragile) sont des
            # contenus distincts a ne pas fusionner - seuls de vrais doublons de
            # tome relie ("Berserk Volume 42" et "Berserk_T42") se rejoignent.
            key = (normalize_name(e.series), e.kind, e.volume)
            groups.setdefault(key, []).append(e)

        def read_rank(e):
            prog = self.store.get_progress(e.path)
            if prog and prog[2]:
                return 2   # termine
            if prog and prog[0] > 0:
                return 1   # entame
            return 0

        result = list(singles)
        for group in groups.values():
            if len(group) == 1:
                result.append(group[0])
            else:
                result.append(min(group, key=lambda e: (-read_rank(e), e.path)))
        return result


    # ----- liaison avec les controleurs -----
    def refresh(self):
        """Relance un scan des dossiers sources (voir ScanController)."""
        self.scanner.refresh()

    @property
    def _scanning(self):
        return self.scanner.scanning

    def _on_scan_started(self):
        if not self._entries:
            self._update_empty_state(False, bool(self._search_text.strip()))

    def _on_scanned(self, paths, cloud_paths):
        self._apply_scan_results(paths, cloud_paths)
        if not self._entries:
            self._update_empty_state(False, bool(self._search_text.strip()))

    def _get_or_fetch_meta(self, e):
        return self.meta.cached_or_fetch(e)

    def _on_series_meta_updated(self, series_key):
        """Auteur de serie arrive : met a jour ses tomes et son dossier, sans
        reconstruire la liste."""
        for path in list(self._path_to_item):
            e = self._entry_by_path.get(path)
            if e is not None and normalize_name(e.series) == series_key:
                self._update_item_meta(path)
        self.list.viewport().update()

    def _bind_cover(self, item, path, role):
        self.covers.bind(item, path, role)

    def _on_cover_ready(self, path):
        self.list.viewport().update()
        self.shelf.list.viewport().update()
        self._refresh_detail_for(path)

    def _apply_scan_results(self, paths, cloud_paths=()):
        """Finalise un scan (cote UI) : construit les entrees a partir des
        chemins dedupliques, persiste l'index, met a jour la surveillance et
        reconstruit la liste. Les empreintes ayant deja ete calculees par le
        worker, key_for/series_override ne touchent ici que le cache.
        `cloud_paths` : tomes presents mais non telecharges (espaces reserves
        cloud), exclus de l'affichage mais proteges de la purge des caches."""
        added = self.store.ensure_added(paths)
        entries = []
        for p in paths:
            stem = Path(p).stem
            sname, svolume, skind = parse_series_ex(stem)
            # regroupement : un tome peut etre detache de tout regroupement
            # automatique (clic droit)
            override = self.store.series_override(p)
            detached = False
            if override == Store.SERIES_DETACHED:
                detached = True
            elif override:
                sname = override
            entries.append(LibraryEntry(
                path=p, title=stem, series=sname, volume=svolume, kind=skind,
                added=added.get(p, 0), detached=detached,
                manual=bool(override) and not detached))
        entries = self._dedupe_by_series_volume(entries)
        # Ne reconstruit la liste QUE si le contenu a change. Pendant le
        # telechargement des tomes cloud, chaque bloc ecrit sur le disque
        # reveille la surveillance des dossiers, qui relance un scan : sans ce
        # garde, la grille entiere etait videe et re-remplie a chaque scan
        # (clignotement permanent) alors que rien de visible n'avait change.
        changed = entries != self._entries
        if changed:
            self._set_entries(entries)
            self.store.save_library_index([e.to_dict() for e in entries])
        # scan reel termine : purge les vignettes/empreintes orphelines (fichiers
        # supprimes ou sortis des dossiers sources depuis le dernier scan). Base
        # sur `paths` (tous les contenus distincts presents), pas sur `entries`
        # (deja fusionnees par serie/tome), pour ne pas purger le cache d'une
        # release deduplifiee mais toujours sur le disque. Les tomes repasses
        # en espace reserve cloud ("Liberer de l'espace") sont toujours la :
        # leurs empreintes/vignettes ne doivent pas etre purgees non plus.
        try:
            self.store.purge_orphan_caches(list(paths) + list(cloud_paths))
        except Exception:
            logging.warning("Purge des caches orphelins en echec", exc_info=True)
        if changed:
            # rafraichissement d'arriere-plan : on conserve la position de
            # defilement (l'utilisateur est peut-etre en train de parcourir la
            # grille pendant qu'un tome telecharge apparait)
            self._rebuild_list()

    def _set_entries(self, entries):
        self._entries = entries
        self._entry_by_path = {e.path: e for e in entries}

    def _load_persisted_index(self):
        """Affiche immediatement le dernier instantane connu de la bibliotheque
        (offline-first) : la fenetre est consultable des le demarrage, sans
        attendre le scan disque (qui reconcilie ensuite en arriere-plan). Les
        fichiers disparus depuis seront retires a la fin du scan.

        Les tomes redevenus de simples espaces reserves cloud depuis le dernier
        scan ("Liberer de l'espace" iCloud/OneDrive) sont ecartes : les afficher
        declencherait la lecture de leur contenu (vignette, empreinte) et donc
        un telechargement bloquant. Le scan qui suit les remettra en file de
        telechargement en arriere-plan."""
        index = self.store.load_library_index()
        entries = [e for e in (LibraryEntry.from_dict(d) for d in index)
                   if e is not None and not is_cloud_placeholder(e.path)]
        if entries:
            self._set_entries(entries)
            self._rebuild_list()

    def update_progress_display(self):
        """Rafraichit l'affichage (progression, tri) au retour du lecteur."""
        self._rebuild_list()


    def _authors_text(self, e):
        """Auteur(s) connus pour ce fichier (cache local uniquement, ne
        declenche pas de recherche) - utilise pour la recherche texte.
        Repli sur l'auteur de la serie (AniList) si le tome n'a pas le sien."""
        meta = self.store.volume_meta(e.path)
        if meta and not meta.get("not_found") and meta.get("authors"):
            return ", ".join(meta["authors"])
        return self._series_author_text(normalize_name(e.series))

    def _series_author_text(self, series_key):
        """Auteur en cache au niveau de la serie (AniList), ou ""."""
        sm = self.store.series_meta(series_key)
        if sm and not sm.get("not_found") and sm.get("authors"):
            return ", ".join(sm["authors"])
        return ""


    def _meta_tooltip_and_author(self, path, meta):
        author_text = ""
        extra = []
        if meta and not meta.get("not_found"):
            if meta.get("authors"):
                author_text = ", ".join(meta["authors"])
                extra.append("Auteur : " + author_text)
            if meta.get("published_year"):
                extra.append(f"Date de sortie : {meta['published_year']}"
                            f" (source : {meta.get('source', '?')})")
        if not author_text:
            # repli sur l'auteur de la serie (recherche AniList au niveau serie)
            e = self._entry_by_path.get(path)
            if e is not None:
                author_text = self._series_author_text(normalize_name(e.series))
                if author_text:
                    extra.insert(0, "Auteur : " + author_text)
        est = self._time_estimate_text(path)
        if est:
            extra.append(est)
        tooltip = path if not extra else path + "\n\n" + "\n".join(extra)
        return tooltip, author_text

    def _time_estimate_text(self, path):
        """Estimation du temps de lecture (restant si le tome est entame, total
        sinon), basee sur le rythme personnel mesure et le nombre de pages
        connu. Renvoie "" tant que le rythme n'a pas ete mesure ou que le
        nombre de pages est inconnu."""
        pace = self.store.median_page_seconds()
        if not pace:
            return ""
        prog = self.store.get_progress(path)
        total = (prog[1] if prog and prog[1] else None) or self.store.page_count(path)
        if not total:
            return ""
        if prog and prog[2]:
            return ""   # termine : rien a estimer
        read = prog[0] if prog else 0
        remaining_pages = max(0, total - read)
        minutes = pace * remaining_pages / 60.0
        if minutes < 1:
            label = "moins d'une minute"
        elif minutes < 60:
            label = f"~{int(round(minutes))} min"
        else:
            label = f"~{int(minutes // 60)} h {int(round(minutes % 60)):02d}"
        prefix = "Temps restant" if (prog and read > 0) else "Temps de lecture"
        return f"{prefix} : {label}"

    def _update_item_meta(self, path):
        """Met a jour l'auteur/tooltip d'un seul item deja affiche, sans
        reconstruire toute la liste (voir _on_meta_done)."""
        meta = self.store.volume_meta(path)
        tooltip, author_text = self._meta_tooltip_and_author(path, meta)
        item = self._path_to_item.get(path)
        if item is not None:
            item.setData(ROLE_AUTHOR_TEXT, author_text)
            item.setToolTip(tooltip)
        if author_text:
            # dossiers de serie abonnes a ce tome : leur auteur vient d'arriver
            for sitem in self._meta_subscribers.get(path, ()):
                sitem.setData(ROLE_AUTHOR_TEXT, author_text)
        self.list.viewport().update()
        self._refresh_detail_for(path)

    def _compute_display_names(self, entries):
        """Une meme serie peut avoir des noms de fichiers formates differemment
        (ex. "Gloutons & Dragons" vs "gloutons-dragons") : ils partagent la
        meme cle normalisee, mais on affiche le nom le plus frequent du groupe
        plutot qu'une variante au hasard."""
        name_votes = {}
        for e in entries:
            if e.detached:
                continue
            key = normalize_name(e.series)
            votes = name_votes.setdefault(key, {})
            votes[e.series] = votes.get(e.series, 0) + 1
        self._series_raw_name = {key: max(votes.items(), key=lambda kv: kv[1])[0]
                                 for key, votes in name_votes.items()}
        # renommage manuel d'une serie (affichage uniquement) prioritaire
        return {key: self.store.series_name(key) or raw
                for key, raw in self._series_raw_name.items()}

    def _rebuild_list(self, keep_position=True):
        """Reconstruit la grille (et la bande « Continuer la lecture »).
        keep_position : conserve le defilement et l'element courant (retour du
        lecteur, action du menu, rescan) au lieu de revenir en haut."""
        pos = self.list_host.position()
        current = self._item_identity(self.list.currentItem())
        self.list.clear()
        self._path_to_item = {}   # reconstruit avec la liste (acces O(1) ensuite)
        self.covers.reset_subscribers()
        self._meta_subscribers = {}
        entries = self._entries

        q = self._search_text.strip().casefold()
        self._series_display_name = self._compute_display_names(self._entries)
        self._info = {e.path: self._entry_info(e) for e in self._entries}

        # une recherche pioche a plat dans tous les tomes (elle "traverse" les
        # dossiers) ; sinon, si le regroupement est actif, on affiche des
        # dossiers de serie (et le contenu d'un dossier ouvert).
        grouping = self._group_series and not q
        if grouping and self._current_series is not None:
            self._rebuild_series_contents(entries)
            self._update_empty_state(self.list.count() > 0, searching=False)
        elif grouping:
            self._rebuild_series_folders(entries)
            self._update_empty_state(self.list.count() > 0, searching=False)
        else:
            # vue a plat : on ajoute TOUS les tomes une fois, puis on masque en
            # place ceux qui ne correspondent pas a la recherche (voir
            # _apply_row_filter). Les frappes suivantes ne reconstruisent donc
            # plus toute la liste - le filtrage est instantane.
            self._current_series = None
            for e in sorted(self._entries,
                            key=lambda e: sort_key(self._sort, self._info[e.path])):
                self._add_item(e)
            self._apply_row_filter()

        self._update_back_button()
        self.list._center_grid()
        self._rebuild_shelf()
        self._update_consent_banner()
        if keep_position:
            self.list.doItemsLayout()   # calcule la plage de defilement
            self._restore_current(current)
            self.list_host.set_position(pos)
        self._update_count()
        self._update_detail()

    def _on_search_changed(self, text):
        prev = self._search_text
        self._search_text = text
        if self._can_filter_in_place(prev, text):
            # meme jeu d'items affiche (vue a plat) : filtrage instantane par
            # masquage de lignes, sans reconstruction ni debounce.
            self._search_timer.stop()
            self._apply_row_filter()
        else:
            # changement structurel (dossiers <-> plat, sortie d'une serie) :
            # reconstruction debouncee
            self._search_timer.start()

    def _can_filter_in_place(self, prev, cur):
        """Le filtrage en place n'est possible que si le jeu d'items affiche ne
        change pas : vue a plat (regroupement desactive), ou recherche deja
        active qui le reste (regroupement actif). Sinon il faut reconstruire."""
        if self._current_series is not None:
            return False
        if not self._group_series:
            return True
        return bool(prev.strip()) and bool(cur.strip())

    def _apply_row_filter(self):
        """Masque/affiche chaque ligne selon la recherche courante (titre, serie
        ou auteur), sans reconstruire la liste."""
        q = self._search_text.strip().casefold()
        any_visible = False
        for i in range(self.list.count()):
            item = self.list.item(i)
            e = self._entry_by_path.get(item.data(ROLE_PATH))
            match = (not q) or (e is not None and (
                q in e.title.casefold() or q in e.series.casefold()
                or q in self._authors_text(e).casefold()))
            if match and e is not None:
                info = self._info.get(e.path)
                match = info is None or matches_status(info.status, self._status_filter)
            self.list.setRowHidden(i, not match)
            any_visible = any_visible or match
        self._update_empty_state(has_any_result=any_visible, searching=bool(q))
        self._update_count()

    def _update_empty_state(self, has_any_result, searching):
        """Bascule entre la grille et le panneau d'etat vide, dont le message
        et le bouton d'action dependent de la situation (premier lancement,
        scan en cours, dossiers sans manga, recherche sans resultat)."""
        self.list_host.setVisible(has_any_result)
        self.empty_panel.setVisible(not has_any_result)
        if has_any_result:
            return
        if not self._entries and not self.store.folders():
            self._set_empty_state(
                "Bienvenue dans Beheread",
                "Ajoutez un dossier contenant vos fichiers CBZ, CBR, EPUB ou PDF pour "
                "constituer votre bibliothèque.\nVous pouvez aussi glisser-déposer "
                "un dossier sur cette fenêtre.",
                "Ajouter un dossier", self._add_folder_dialog)
        elif not self._entries and self._scanning:
            self._set_empty_state("Analyse de vos dossiers…",
                                  "Vos mangas apparaîtront dans un instant.")
        elif not self._entries:
            self._set_empty_state(
                "Aucun manga trouvé",
                "Vos dossiers sources ne contiennent aucun fichier CBZ, CBR, EPUB ou PDF.",
                "Gérer les dossiers", self.manage_folders)
        elif searching:
            text = f"Aucun manga ne correspond à « {self._search_text.strip()} »"
            if self._status_filter != ALL:
                text += f" parmi les mangas « {self._status_label()} »"
            self._set_empty_state("Aucun résultat", text + ".",
                                  "Effacer la recherche", self.search_edit.clear)
        elif self._status_filter != ALL:
            self._set_empty_state(
                f"Aucun manga « {self._status_label()} »",
                "Aucun élément ne correspond au filtre choisi.",
                "Afficher tous les mangas", lambda: self._set_status_filter(ALL))
        else:
            self._set_empty_state("Aucun manga à afficher", "")


    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._help.isVisible():
            self._help.show_centered()


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
        """Contenu d'un dossier de serie ouvert : ses tomes, tries par numero."""
        grp = self._group_entries(entries).get(self._current_series)
        if not grp:
            # la serie a disparu (fichiers retires) : on remonte au niveau racine
            self._current_series = None
            self._rebuild_series_folders(entries)
            return
        # dans une serie, l'ordre des tomes reste l'ordre de lecture (numero)
        for e in sorted(grp, key=self._volume_sort_key):
            if matches_status(self._info[e.path].status, self._status_filter):
                self._add_item(e)

    def _volume_sort_key(self, e):
        return (e.volume if e.volume is not None else -1, e.title.casefold())

    def _add_item(self, e):
        item = QListWidgetItem(e.title)
        item.setData(ROLE_PATH, e.path)
        # declenche (ou reutilise) la recherche de metadonnees pour toute la
        # bibliotheque, pas seulement quand on trie par auteur/date : l'info
        # se remplit progressivement en arriere-plan des l'affichage, sans
        # reconstruire la liste a chaque reponse (voir _on_meta_done).
        meta = self._get_or_fetch_meta(e)
        tooltip, author_text = self._meta_tooltip_and_author(e.path, meta)
        item.setData(ROLE_AUTHOR_TEXT, author_text)
        item.setToolTip(tooltip)
        self._apply_progress(item, e.path)
        self.list.addItem(item)
        self._path_to_item[e.path] = item
        self._bind_cover(item, e.path, ROLE_PIXMAP)

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

        read, count, frac, finished = self._series_progress(group)
        item.setData(ROLE_FRACTION, frac)
        item.setData(ROLE_FINISHED, finished)
        if finished:
            item.setData(ROLE_PROG_TEXT, "Série terminée")
        elif read > 0:
            item.setData(ROLE_PROG_TEXT, f"{read}/{count} tomes lus")
        else:
            item.setData(ROLE_PROG_TEXT, f"{count} tomes")

        # auteur : depuis le cache des tomes ; la recherche est declenchee pour
        # le tome vedette et l'item s'abonne au resultat (voir _update_item_meta)
        self._get_or_fetch_meta(rotated[0])
        author = self._series_author(vols)
        item.setData(ROLE_AUTHOR_TEXT, author)
        self._meta_subscribers.setdefault(rotated[0].path, []).append(item)

        tooltip = f"{display}  ·  {count} tomes"
        if author:
            tooltip += f"\nAuteur : {author}"
        item.setToolTip(tooltip)

        self.list.addItem(item)
        for role, path in zip((ROLE_PIXMAP, ROLE_PIXMAP2, ROLE_PIXMAP3), cover_paths):
            self._bind_cover(item, path, role)

    def _series_progress(self, group):
        """Agrege la progression d'une serie : nombre de tomes termines,
        total, fraction lue, et si toute la serie est terminee."""
        count = len(group)
        read = 0
        for e in group:
            prog = self.store.get_progress(e.path)
            if prog and prog[2]:
                read += 1
        frac = read / count if count else 0.0
        return read, count, frac, (read == count and count > 0)


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
            self._search_timer.stop()
            self.search_edit.blockSignals(True)
            self.search_edit.clear()
            self.search_edit.blockSignals(False)
            self._search_text = ""
        if changed:
            self._rebuild_list(keep_position=False)
        self.list.setFocus()

    def _update_back_button(self):
        if self._current_series is not None:
            name = self._series_display_name.get(self._current_series, "Serie")
            self.btn_back.setText(name)
            self.btn_back.setToolTip("Retour à la bibliothèque   Échap")
            self.btn_back.show()
        else:
            self.btn_back.hide()

    # ----- interne -----
    def _apply_progress(self, item: QListWidgetItem, path: str):
        prog = self.store.get_progress(path)
        if prog:
            page, total, finished = prog
            frac = (page + 1) / total if total else 0.0
            item.setData(ROLE_FRACTION, min(1.0, frac))
            item.setData(ROLE_FINISHED, finished)
            if total:
                txt = "Terminé" if finished else f"Page {page + 1} / {total}"
                item.setData(ROLE_PROG_TEXT, txt)
        else:
            item.setData(ROLE_FRACTION, 0.0)
            item.setData(ROLE_FINISHED, False)
            item.setData(ROLE_PROG_TEXT, "")

    def _cover_display_size(self) -> QSize:
        """Taille (pixels physiques) des couvertures gardees en memoire : la
        plus grande case affichable (curseur au maximum) sur l'ecran le plus
        dense, plafonnee a la resolution du cache disque. Sur un ecran a 100%,
        1,5x la taille de reference suffit - 4x moins de RAM qu'un 3x fixe
        (~0,45 Mo au lieu de ~1,8 Mo par couverture)."""
        dpr = max((s.devicePixelRatio() for s in QGuiApplication.screens()), default=1.0)
        factor = min(float(THUMB_SCALE), self.GRID_SCALE_MAX / 100.0 * dpr)
        return QSize(round(THUMB_W * factor), round(THUMB_H * factor))


    def _on_activated(self, item: QListWidgetItem):
        if item.data(ROLE_IS_SERIES):
            self._enter_series(item.data(ROLE_SERIES_KEY))
            return
        self.mangaActivated.emit(item.data(ROLE_PATH))

    def _series_paths(self, key):
        """Chemins de tous les tomes du dossier de serie `key` (memes membres
        que ceux affiches par le dossier : regroupement automatique, tomes
        detaches exclus)."""
        grp = self._group_entries(self._entries).get(key) or []
        return [e.path for e in grp]


    # ----- informations de tri / statut -----
    def _entry_info(self, e):
        path = e.path
        meta = self.store.volume_meta(path)
        meta = None if (meta and meta.get("not_found")) else meta
        series_key = None if e.detached else normalize_name(e.series)
        year = (meta or {}).get("published_year")
        if not year and series_key:
            sm = self.store.series_meta(series_key)
            if sm and not sm.get("not_found"):
                year = sm.get("published_year")
        prog = self.store.get_progress(path)
        return VolumeInfo(
            path=path, key=self.store.key_for(path), title=e.title,
            series_key=series_key, volume=e.volume,
            status=volume_status(prog), last_read=self.store.progress_ts(path),
            added=e.added, author=self._authors_text(e), year=year)

    @staticmethod
    def _item_identity(item):
        if item is None:
            return None
        if item.data(ROLE_IS_SERIES):
            return ("series", item.data(ROLE_SERIES_KEY))
        return ("path", item.data(ROLE_PATH))

    def _restore_current(self, identity):
        if identity is None:
            return
        kind, value = identity
        for i in range(self.list.count()):
            item = self.list.item(i)
            if self._item_identity(item) == (kind, value) and not self.list.isRowHidden(i):
                self.list.setCurrentItem(item)
                return

    # ----- « Continuer la lecture » -----
    def _rebuild_shelf(self):
        lst = self.shelf.list
        lst.clear()
        show = (self._show_continue and not self._search_text.strip()
                and self._current_series is None and self._status_filter == ALL)
        picks = continue_reading(self._info.values(), self.store.continue_dismissed()) if show else []
        for info, kind in picks:
            item = QListWidgetItem(info.title)
            item.setData(ROLE_PATH, info.path)
            self._apply_progress(item, info.path)
            if kind == "next":
                item.setData(ROLE_PROG_TEXT, "À suivre")
                item.setToolTip(f"{info.title}\nProchain tome à lire")
            else:
                item.setToolTip(f"{info.title}\nReprendre la lecture")
            lst.addItem(item)
            self._bind_cover(item, info.path, ROLE_PIXMAP)
        self.shelf.setVisible(bool(picks))


