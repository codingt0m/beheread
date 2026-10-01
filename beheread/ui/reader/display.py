"""Reglages d'affichage : recadrage des marges, planches doubles, Ambilight, fondu entre les pages, mise a l'echelle, zoom, sens de lecture.

Mixin de ReaderWidget : ces methodes partagent l'etat du lecteur
(self.page, self.cache, self.store...) ; elles sont regroupees ici par
responsabilite."""

from pathlib import Path

from PySide6.QtCore import (
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QPixmap

from beheread.core.series import normalize_name, parse_series
from beheread.infra.storage import Store
from beheread.ui.reader.constants import (
    AMBIENT_MS,
    AMBIENT_STEP_MS,
    FIT_HEIGHT,
    FIT_WIDTH,
    SCALED_CACHE_LIMIT,
    TRANSITION_MS,
    TRANSITION_STEP_MS,
)
from beheread.ui.reader.imaging import average_color, compute_content_rect, darken


class DisplayMixin:
    # ------------------------------------------------------------ pages
    def _content_rect(self, index):
        """QRect du contenu utile (marges rognees) pour cette page, ou None si
        aucun recadrage pertinent. Calcule une fois puis mis en cache."""
        if index in self._crop_cache:
            return self._crop_cache[index]
        img = self.cache.get(index)
        rect = compute_content_rect(img) if img and not img.isNull() else None
        self._crop_cache[index] = rect
        return rect

    def _content_margins(self, index):
        """Marges de contenu (gauche, haut, droite, bas) en fractions [0,1) des
        dimensions de la page, ou None si aucun recadrage pertinent."""
        img = self.cache.get(index)
        rect = self._content_rect(index)
        if img is None or img.isNull() or rect is None:
            return None
        w, h = img.width(), img.height()
        return (rect.left() / w, rect.top() / h,
                (w - rect.right() - 1) / w, (h - rect.bottom() - 1) / h)

    def _rect_from_margins(self, index, margins):
        img = self.cache[index]
        w, h = img.width(), img.height()
        l, t, r, b = margins
        x = int(round(l * w))
        y = int(round(t * h))
        x1 = int(round((1 - r) * w))
        y1 = int(round((1 - b) * h))
        return QRect(x, y, max(1, x1 - x), max(1, y1 - y))

    def _display_crops(self, indices):
        """Rectangles de recadrage a appliquer pour l'affichage courant.
        En double page, les deux pages partagent le MEME niveau de recadrage :
        on retient, bord par bord, la marge la plus faible des deux (le
        recadrage le moins agressif), pour que les deux planches restent
        alignees et a la meme echelle."""
        if not self.smart_crop:
            return {i: None for i in indices}
        if len(indices) == 1:
            return {indices[0]: self._content_rect(indices[0])}
        margins = [self._content_margins(i) for i in indices]
        if any(m is None for m in margins):
            # au moins une page ne se recadre pas -> aucune des deux (le moins agressif)
            return {i: None for i in indices}
        shared = tuple(min(m[k] for m in margins) for k in range(4))
        return {i: self._rect_from_margins(i, shared) for i in indices}

    def _effective_size(self, index):
        """Taille de la source affichee pour cette page (rognee si recadrage
        actif), ou None si l'image n'est pas encore disponible. Sert a la
        detection des planches doubles (appairage), independamment du partage
        de recadrage entre deux pages voisines."""
        img = self.cache.get(index)
        if img is None or img.isNull():
            return None
        if self.smart_crop:
            r = self._content_rect(index)
            if r is not None:
                return r.size()
        return img.size()

    def _is_spread(self, index):
        """Une image plus large que haute couvre deja une double page (scan
        de planche double) : elle doit s'afficher seule, jamais couplee."""
        s = self._effective_size(index)
        return s is not None and s.width() > s.height()

    def _ambient_color_for(self, index):
        """Couleur de fond Ambilight pour cette page (moyenne assombrie),
        mise en cache. None si la page n'est pas encore decodee."""
        if index in self._ambient_cache:
            return self._ambient_cache[index]
        img = self.cache.get(index)
        if img is None or img.isNull():
            return None
        color = darken(average_color(img))
        self._ambient_cache[index] = color
        return color

    def _update_ambient_target(self, animate=True):
        """Determine la couleur de fond visee (celle de la page courante en
        Ambilight, sinon le fond neutre du theme) et lance la transition."""
        if self._theme_bg is None:
            return
        if self.ambilight:
            idx = self._current_indices()[0]
            color = self._ambient_color_for(idx)
            target = color if color is not None else self._theme_bg
        else:
            target = self._theme_bg
        self._set_bg_target(target, animate=animate)

    def _set_bg_target(self, color: QColor, animate=True):
        if self._bg_color is not None and color.getRgb() == self._bg_color.getRgb():
            return
        if not animate or self._bg_color is None:
            self._bg_timer.stop()
            self._bg_color = QColor(color)
            self.update()
            return
        self._bg_from = QColor(self._bg_color)
        self._bg_to = QColor(color)
        self._bg_progress = 0.0
        self._bg_timer.start(AMBIENT_STEP_MS)

    def _step_bg(self):
        self._bg_progress = min(1.0, self._bg_progress + AMBIENT_STEP_MS / AMBIENT_MS)
        t = self._bg_progress
        r = self._bg_from.red() + (self._bg_to.red() - self._bg_from.red()) * t
        g = self._bg_from.green() + (self._bg_to.green() - self._bg_from.green()) * t
        b = self._bg_from.blue() + (self._bg_to.blue() - self._bg_from.blue()) * t
        self._bg_color = QColor(int(r), int(g), int(b))
        if self._bg_progress >= 1.0:
            self._bg_timer.stop()
        self.update()

    # ------------------------------------------------------------ transition
    def _start_transition(self):
        """Fige les pixmaps de la page courante (positionnes) pour les fondre
        au-dessus de la nouvelle page pendant TRANSITION_MS. Pas de self.grab()
        (qui allouerait tout le widget et engloberait le HUD dans le fondu)."""
        if self.width() <= 0 or self.height() <= 0 or not self._last_frame:
            self._prev_frame = None
            return
        self._prev_frame = self._last_frame
        self._transition_progress = 1.0
        self._transition_timer.start(TRANSITION_STEP_MS)

    def _step_transition(self):
        self._transition_progress -= TRANSITION_STEP_MS / TRANSITION_MS
        if self._transition_progress <= 0:
            self._transition_progress = 0.0
            self._transition_timer.stop()
            self._prev_frame = None
        self.update()

    def _cancel_transition(self):
        """Arrete net un fondu en cours (timer + frame figee)."""
        self._transition_timer.stop()
        self._transition_progress = 0.0
        self._prev_frame = None

    def _scaled_pixmap(self, index, crop, target_w, target_h, dpr):
        """Pixmap de la page (recadree selon `crop` si fourni) mis a l'echelle a
        la taille cible, memorise par (index, recadrage, taille). Evite de
        refaire un rescale couteux a chaque frame (fondu, panoramique)."""
        crop_key = (crop.x(), crop.y(), crop.width(), crop.height()) if crop is not None else None
        key = (index, crop_key, target_w, target_h)
        pm = self._scaled_cache.get(key)
        if pm is not None:
            return pm
        img = self.cache[index]
        src = img.copy(crop) if crop is not None else img
        pm = QPixmap.fromImage(src).scaled(
            QSize(target_w, target_h), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        self._scaled_cache[key] = pm
        self._scaled_order.append(key)
        while len(self._scaled_order) > SCALED_CACHE_LIMIT:
            self._scaled_cache.pop(self._scaled_order.pop(0), None)
        return pm

    def _clear_scaled_cache(self):
        self._scaled_cache.clear()
        self._scaled_order.clear()

    # --- bascules (partagees par le clavier et les chips du HUD) -----------
    # Chaque choix est enregistre comme preference du lecteur : il vaut pour
    # tous les mangas, pas seulement pour celui qui est ouvert. Seul le sens
    # de lecture reste propre a chaque serie (voir _initial_manga_mode).
    def toggle_double_page(self):
        self.double_page = not self.double_page
        self.store.set_reader_pref("double_page", self.double_page)
        self._go_to(self.page)

    def toggle_manga_mode(self):
        self.manga_mode = not self.manga_mode
        self.store.set_reader_pref("manga_mode", self.manga_mode)
        self.store.set_reading_direction(self.path, self._series_key, self.manga_mode)
        self._update_hud()
        self.update()

    def _resolve_series_key(self):
        """Cle de regroupement de serie pour ce tome (meme logique que la
        bibliotheque : override manuel prioritaire, sinon numero de tome
        detecte dans le nom de fichier). None si le tome est seul (pas de
        serie), auquel cas le sens de lecture est memorise par tome."""
        override = self.store.series_override(self.path)
        if override == Store.SERIES_DETACHED:
            return None
        if override:
            return normalize_name(override)
        sname, svolume = parse_series(Path(self.path).stem)
        if svolume is None:
            return None
        return normalize_name(sname)

    def _detect_manga_mode(self):
        """Sens de lecture detecte automatiquement, sans requete reseau (le
        lecteur reste hors ligne) - trois paliers, par ordre de priorite :

        1. "manga" : genre AniList deja mis en cache (par la bibliotheque, au
           survol/scan) pour ce tome ou sa serie, avec pays d'origine connu -
           trouve dans la base manga d'AniList et pays hors Coree/Chine ->
           droite -> gauche (couvre un manga francais comme Radiant, malgre
           son pays d'origine) ; manhwa/manhua (Coree/Chine), presque
           toujours numeriques et lus gauche -> droite, font exception.
        2. "japon" : trouve dans la meme base mais sans pays d'origine
           renseigne - on suppose Japon par defaut (cas tres largement
           majoritaire) -> droite -> gauche.
        3. "xml" : rien en cache AniList pour ce tome/cette serie (jamais
           interroge) -> repli sur ComicInfo.xml (champ Manga), local a
           l'archive.

        Rien de neuf n'est interroge ici pour AniList - seul le cache local
        (meta_cache.json) est lu. None si aucune de ces sources ne donne
        d'indice exploitable."""
        for cached in (self.store.volume_meta(self.path),
                      self.store.series_meta(self._series_key) if self._series_key else None):
            if not cached or cached.get("not_found"):
                continue
            if "country" not in cached:
                continue   # cache ComicInfo/Google Books : pas une entree AniList
            country = (cached.get("country") or "").upper()
            if country:
                return country not in ("KR", "CN")   # palier "manga"
            return True                              # palier "japon" (pays inconnu)

        try:
            info = self.archive.read_comicinfo()
        except Exception:
            info = None
        direction = (info or {}).get("reading_direction")   # palier "xml"
        if direction == "rtl":
            return True
        if direction == "ltr":
            return False
        return None

    def _initial_manga_mode(self):
        """Priorite : choix explicite de l'utilisateur (par serie si ce tome
        en fait partie, sinon par tome) > detection automatique (ComicInfo.xml)
        > reglage global par defaut."""
        saved = self.store.reading_direction(self.path, self._series_key)
        if saved is not None:
            return saved
        detected = self._detect_manga_mode()
        if detected is not None:
            return detected
        return bool(self.store.reader_pref("manga_mode", True))

    def cycle_fit_mode(self):
        self.fit_mode = FIT_WIDTH if self.fit_mode == FIT_HEIGHT else FIT_HEIGHT
        self.store.set_reader_pref("fit_mode", self.fit_mode)
        self.zoom = 1.0
        self._clear_scaled_cache()
        self._go_to(self.page)

    def toggle_smart_crop(self):
        self.smart_crop = not self.smart_crop
        self.store.set_reader_pref("smart_crop", self.smart_crop)
        self._clear_scaled_cache()
        self._update_hud()
        self.update()

    def toggle_ambilight(self):
        self.ambilight = not self.ambilight
        self.store.set_reader_pref("ambilight", self.ambilight)
        self._update_ambient_target()
        self._update_hud()

    def _set_zoom(self, value: float):
        self.zoom = max(0.2, min(6.0, value))
        self._clear_scaled_cache()   # la taille cible change avec le zoom
        self._update_hud()
        self.update()
