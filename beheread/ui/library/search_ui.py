"""Recherche de la bibliotheque : saisie, index, resultats.

Mixin de LibraryWidget : ces methodes partagent l'etat du widget
(self.list, self.store, self._entries...) ; voir widget.py."""



from beheread.core.search import known_titles
from beheread.core.series import (
    normalize_name,
)


class SearchMixin:
    # ----- recherche -----
    def _on_search_changed(self, text):
        """Chaque frappe filtre en place (aucune reconstruction, aucun delai) :
        la recherche est resolue par l'index, puis seules les lignes qui
        changent d'etat sont masquees ou affichees."""
        was_searching = self._search_hits is not None
        self._search_text = text
        if self._current_series is not None:
            # la recherche porte sur toute la bibliotheque : depuis un dossier
            # de serie ouvert, on revient a la racine pour en montrer les
            # resultats (et y revenir a l'endroit quitte en l'effacant)
            if not was_searching:
                self._pre_search_position = self._root_position
            self._current_series = None
            self._rebuild_list(keep_position=False)
        else:
            if not was_searching:
                self._pre_search_position = (
                    self.list_host.position(), self._item_identity(self.list.currentItem()))
            self._run_search()
            self._apply_filter()
        if self._search_hits is not None:
            self.list_host.set_position(0)   # les resultats commencent en haut
        elif was_searching:
            self._restore_pre_search_position()

    def _restore_pre_search_position(self):
        saved, self._pre_search_position = self._pre_search_position, None
        if saved is None:
            return
        pos, current = saved
        self.list.doItemsLayout()   # calcule la plage de defilement
        self._restore_current(current)
        self.list_host.set_position(pos)

    def _run_search(self):
        """Resout la recherche courante en jeu de chemins de tomes
        (self._search_hits), ou None sans recherche active."""
        result = None
        if self._search_text.strip():
            self._ensure_search_index()
            result = self._search_index.search(self._search_text)
        self._search_hits = None if result is None else result.ids
        self._search_approx = result is not None and result.approximate

    def _ensure_search_index(self):
        """Aligne l'index sur la bibliotheque, a la demande : rien n'est indexe
        tant qu'aucune recherche n'est faite, et les tomes inchanges depuis la
        derniere indexation ne coutent qu'une comparaison."""
        if self._search_index_dirty:
            self._search_index.replace_all(
                {e.path: self._search_texts(e) for e in self._entries})
            self._search_index_dirty = False

    def _search_texts(self, e):
        """Champs indexes d'un tome : nom du fichier, serie (nom deduit et nom
        affiche), auteurs du tome et de la serie, titres connus de l'oeuvre.
        Metadonnees en cache uniquement : aucune recherche declenchee."""
        info = self._info.get(e.path)
        key = info.series_key if info is not None and info.series_key else normalize_name(e.series)
        meta = self.store.volume_meta(e.path)
        series_meta = self.store.series_meta(key)
        texts = [e.title, self._display_title(e), e.series, self._series_display_name.get(key)]
        for m in (meta, series_meta):
            if m and not m.get("not_found"):
                texts.extend(m.get("authors") or ())
            texts.extend(known_titles(m))
        return texts

    def _search_meta_changed(self):
        """Metadonnees (auteur, titres) arrivees en arriere-plan : l'index est
        a rafraichir, et la recherche en cours a relancer (un tome peut
        desormais y correspondre)."""
        self._search_index_dirty = True
        if self._search_hits is not None:
            self._run_search()
            self._apply_filter()
