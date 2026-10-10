"""Menus contextuels (clic droit) de la grille et de la bande « Continuer la lecture ».

Mixin de LibraryWidget : ces methodes partagent l'etat du widget
(self.list, self.store, self._entries...) ; elles sont regroupees ici par
responsabilite pour garder chaque fichier lisible."""


from PySide6.QtWidgets import QMenu

from beheread import platforms
from beheread.core.library_model import FINISHED
from beheread.infra.storage import Store

# modules extraits (voir chacun) : constantes de rendu, delegates, dialogues et
# taches d'arriere-plan. LibraryWidget (ci-dessous) orchestre le tout.
from beheread.ui.library.constants import ROLE_IS_SERIES, ROLE_PATH, ROLE_SERIES_KEY


class MenusMixin:
    # ----- menu contextuel (clic droit), simple ou multi-selection -----
    def _show_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        # dossier de serie : pas d'action par tome (il en represente plusieurs),
        # mais on permet de supprimer la serie entiere d'un coup.
        if item.data(ROLE_IS_SERIES):
            self._show_series_context_menu(item, pos)
            return
        if item not in self.list.selectedItems():
            self.list.clearSelection()
            item.setSelected(True)
            self.list.setCurrentItem(item)

        items = [it for it in self.list.selectedItems()
                 if not it.data(ROLE_IS_SERIES)]
        if not items:
            return
        n = len(items)

        menu = QMenu(self)
        act_reset = menu.addAction(
            "Réinitialiser la progression" if n == 1 else f"Réinitialiser la progression ({n})")
        act_finished = menu.addAction(
            "Marquer comme lu" if n == 1 else f"Marquer {n} mangas comme lus")
        # "Marquer comme non lu" : annule un marquage "termine" (accidentel ou
        # non) sans perdre la page courante - propose seulement si au moins un
        # tome selectionne est effectivement marque termine.
        paths = [it.data(ROLE_PATH) for it in items]
        act_unread = None
        if any((self.store.get_progress(p) or (0, 0, False))[2] for p in paths):
            act_unread = menu.addAction(
                "Marquer comme non lu" if n == 1 else f"Marquer {n} mangas comme non lus")
        menu.addSeparator()
        act_reload_meta = menu.addAction(
            "Recharger les métadonnées" if n == 1 else f"Recharger les métadonnées ({n})")
        act_edit = menu.addAction("Modifier les informations…") if n == 1 else None
        act_move = menu.addAction(
            "Déplacer vers une série…" if n == 1 else f"Déplacer {n} mangas vers une série…")
        act_rename = menu.addAction("Renommer le fichier…") if n == 1 else None
        act_explorer = menu.addAction(platforms.REVEAL_LABEL) if n == 1 else None

        # --- regroupement en serie ---
        act_detach = act_restore = None
        if any(self._is_grouped_in_series(p) for p in paths):
            menu.addSeparator()
            act_detach = menu.addAction(
                "Sortir de la série" if n == 1 else f"Sortir {n} mangas de leur série")
        if any(self.store.series_override(p) is not None for p in paths):
            if act_detach is None:
                menu.addSeparator()
            act_restore = menu.addAction("Rétablir le regroupement automatique")

        menu.addSeparator()
        act_delete = menu.addAction(
            "Supprimer le manga…" if n == 1 else f"Supprimer {n} mangas…")

        chosen = menu.exec(self.list.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_detach:
            for p in paths:
                if self._is_grouped_in_series(p):
                    self.store.set_series_override(p, Store.SERIES_DETACHED)
            self.refresh()
        elif chosen == act_restore:
            for p in paths:
                self.store.clear_series_override(p)
            self.refresh()
        elif chosen == act_reset:
            for it in items:
                self.store.remove_progress(it.data(ROLE_PATH))
            self._rebuild_list()
        elif chosen == act_finished:
            for it in items:
                self._mark_finished(it.data(ROLE_PATH))
            self._rebuild_list()
        elif act_unread is not None and chosen == act_unread:
            for it in items:
                self._mark_unread(it.data(ROLE_PATH))
            self._rebuild_list()
        elif chosen == act_reload_meta:
            self._reload_meta([it.data(ROLE_PATH) for it in items])
        elif act_edit is not None and chosen == act_edit:
            self._edit_volume_info(items[0].data(ROLE_PATH))
        elif chosen == act_move:
            self._move_to_series(paths)
        elif act_rename is not None and chosen == act_rename:
            self._rename_tome(items[0].data(ROLE_PATH))
        elif act_explorer is not None and chosen == act_explorer:
            self._show_in_explorer(items[0].data(ROLE_PATH))
        elif chosen == act_delete:
            self._delete_many([it.data(ROLE_PATH) for it in items])

    def _show_series_context_menu(self, item, pos):
        """Menu contextuel d'un dossier de serie : suppression de tous ses
        tomes en une fois (la confirmation liste les fichiers concernes)."""
        key = item.data(ROLE_SERIES_KEY)
        paths = self._series_paths(key)
        if not paths:
            return
        n = len(paths)
        display = self._series_display_name.get(key) or item.text()

        menu = QMenu(self)
        act_open = menu.addAction("Ouvrir la série")
        finished = all(getattr(self._info.get(p), "status", None) == FINISHED for p in paths)
        act_read = None if finished else menu.addAction("Marquer la série comme lue")
        menu.addSeparator()
        act_edit = menu.addAction("Modifier les informations…")
        act_rename = menu.addAction("Renommer la série…")
        act_merge = menu.addAction("Fusionner avec une autre série…")
        act_anilist = (menu.addAction("Associer à AniList…")
                       if self.tracker is not None and self.tracker.connected() else None)
        menu.addSeparator()
        act_delete = menu.addAction(f"Supprimer la série ({n} tomes)…")
        chosen = menu.exec(self.list.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_open:
            self._enter_series(key)
        elif act_read is not None and chosen == act_read:
            self._mark_series_finished(key)
        elif chosen == act_edit:
            self._edit_series_info(key)
        elif chosen == act_rename:
            self._rename_series(key)
        elif act_anilist is not None and chosen == act_anilist:
            self._associate_anilist(key, paths[0])
        elif chosen == act_merge:
            self._merge_series(key)
        elif chosen == act_delete:
            self._delete_many(paths, series_label=display)

    def _show_shelf_menu(self, path, global_pos):
        menu = QMenu(self)
        act_open = menu.addAction("Ouvrir")
        act_hide = menu.addAction("Masquer de « Continuer la lecture »")
        # seulement pour un tome entame : « A suivre » propose un tome non
        # commence, qui n'a pas de progression a effacer
        act_reset = (menu.addAction("Réinitialiser la progression")
                     if self.store.get_progress(path) is not None else None)
        act_read = menu.addAction("Marquer comme lu")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen == act_open:
            self.mangaActivated.emit(path)
        elif chosen == act_hide:
            self.store.dismiss_continue(path)
            self._rebuild_list()
        elif chosen == act_reset:
            self.store.remove_progress(path)
            self._rebuild_list()
        elif chosen == act_read:
            self._mark_finished(path)
            self._rebuild_list()
