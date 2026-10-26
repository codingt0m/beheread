"""Menus contextuels (clic droit) de la grille et de la bande « Continuer la lecture ».

Tous suivent le meme ordre (maquette M1 validee) : ouvrir, progression,
informations et rangement (sous-menus Ranger et Fichier), puis Supprimer,
seul dans son groupe. Le panneau d'informations ouvre ces memes menus par
son bouton « ⋯ » (voir detail_panel.py).

Mixin de LibraryWidget : ces methodes partagent l'etat du widget
(self.list, self.store, self._entries...) ; elles sont regroupees ici par
responsabilite pour garder chaque fichier lisible."""


import logging

from PySide6.QtWidgets import QMenu, QMessageBox

from beheread import platforms
from beheread.core import units
from beheread.core.library_model import FINISHED
from beheread.core.series import normalize_name
from beheread.i18n import tr
from beheread.infra import virtual
from beheread.infra.storage import Store

# modules extraits (voir chacun) : constantes de rendu, delegates, dialogues et
# taches d'arriere-plan. LibraryWidget (ci-dessous) orchestre le tout.
from beheread.ui.library.constants import (
    ROLE_IS_SERIES,
    ROLE_MISSING,
    ROLE_PATH,
    ROLE_SECTION,
    ROLE_SERIES_KEY,
)

# Extensions des menus de tome et de serie : fonctions (menu, library, kind,
# target) appelees juste avant « Supprimer… », qui y ajoutent leurs actions
# (menu.separator(), menu.add(...)). kind : "volume" (target : chemins
# selectionnes) ou "series" (target : cle de la serie). Une extension qui
# plante est ignoree : le menu s'ouvre quand meme.
EXTENSIONS = []


def register_extension(fn):
    """Ajoute une extension (une seule fois par fonction)."""
    if fn not in EXTENSIONS:
        EXTENSIONS.append(fn)


log = logging.getLogger(__name__)


class ActionMenu:
    """QMenu dont chaque action porte sa fonction : une action n'existe que
    si elle est ajoutee, et exec() appelle celle qui a ete choisie (plus de
    variables act_x = None ni de chaine de elif a tenir en phase)."""

    def __init__(self, parent):
        self.menu = QMenu(parent)
        self._handlers = {}

    def add(self, label, handler, menu=None, checked=None, default=False):
        """Ajoute `label` au menu (ou au sous-menu `menu`) ; `checked` :
        action cochable, dans cet etat ; `default` : action principale (en gras)."""
        act = (menu or self.menu).addAction(label)
        if checked is not None:
            act.setCheckable(True)
            act.setChecked(checked)
        if default:
            self.menu.setDefaultAction(act)
        self._handlers[act] = handler
        return act

    def on(self, act, handler):
        """Fonction d'une action creee ailleurs (dossiers du sous-menu Ranger)."""
        self._handlers[act] = handler

    def separator(self):
        """Separe deux groupes ; sans effet en tete de menu ou apres un
        separateur (un groupe vide n'en laisse pas deux a la suite)."""
        actions = self.menu.actions()
        if actions and not actions[-1].isSeparator():
            self.menu.addSeparator()

    def submenu(self, label):
        return self.menu.addMenu(label)

    def extend(self, library, kind, target):
        """Laisse les extensions enregistrees completer le menu."""
        for fn in list(EXTENSIONS):
            try:
                fn(self, library, kind, target)
            except Exception:
                log.exception("extension de menu ignoree")

    def exec(self, global_pos):
        handler = self._handlers.get(self.menu.exec(global_pos))
        if handler is not None:
            handler()


class MenusMixin:
    # ----- menu contextuel (clic droit), simple ou multi-selection -----
    def _show_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None or item.data(ROLE_MISSING) or item.data(ROLE_SECTION):
            return
        global_pos = self.list.viewport().mapToGlobal(pos)
        # dossier de serie : actions sur toute la serie
        if item.data(ROLE_IS_SERIES):
            self._show_series_menu(item.data(ROLE_SERIES_KEY), global_pos)
            return
        if item not in self.list.selectedItems():
            self.list.clearSelection()
            item.setSelected(True)
            self.list.setCurrentItem(item)
        self._show_volume_menu([it.data(ROLE_PATH) for it in self.list.selectedItems()
                                if not it.data(ROLE_IS_SERIES)], global_pos)

    def _show_volume_menu(self, paths, global_pos):
        """Menu d'un tome (ou chapitre), ou d'une selection de plusieurs."""
        # tome virtuel : son propre menu (ce n'est pas un fichier)
        if len(paths) == 1 and virtual.is_virtual(paths[0]):
            self._show_virtual_menu(paths[0], global_pos)
            return
        paths = [p for p in paths if not virtual.is_virtual(p)]
        if not paths:
            return
        n = len(paths)
        one = n == 1
        entries = [self._entry_by_path.get(p) for p in paths]
        chapters = sum(1 for e in entries if e is not None and self._unit(e) == units.CHAPTER)
        count = units.count_text(n - chapters, chapters)   # « 3 tomes · 2 chapitres »
        # tome d'un serveur de lecture : pas de fichier sur ce disque
        remote = any(self._is_remote(p) for p in paths)
        progress = [self.store.get_progress(p) for p in paths]
        finished = [bool(pr and pr[2]) for pr in progress]

        def each_then_rebuild(fn):
            def run():
                for p in paths:
                    fn(p)
                self._rebuild_list()
            return run

        m = ActionMenu(self)
        # --- ouvrir ---
        if one:
            m.add(tr("Ouvrir"), lambda: self.mangaActivated.emit(paths[0]), default=True)
        # plusieurs chapitres d'une meme serie : les regrouper en tome virtuel
        if (n >= 2 and chapters == n
                and len({normalize_name(e.series) for e in entries}) == 1):
            m.add(tr("Regrouper en tome…"), lambda: self._group_chapters(paths))

        # --- progression : une seule bascule lu / non lu selon l'etat (les
        # deux pour une selection melangee) ---
        m.separator()
        if not all(finished):
            m.add(tr("Marquer comme lu") if one else tr("Marquer {count} comme lus", count=count),
                  each_then_rebuild(self._mark_finished))
        # annule un marquage "termine" (accidentel ou non) sans perdre la page courante
        if any(finished):
            m.add(tr("Marquer comme non lu") if one
                  else tr("Marquer {count} comme non lus", count=count),
                  each_then_rebuild(self._mark_unread))
        if any(pr is not None for pr in progress):
            m.add(tr("Réinitialiser la progression…"), lambda: self._confirm_reset(paths, count))

        # --- informations et rangement ---
        m.separator()
        if one:
            m.add(tr("Modifier les informations…"), lambda: self._edit_volume_info(paths[0]))
            m.add(tr("Choisir la couverture…"), lambda: self._choose_cover(paths[0]))
        ranger = m.submenu(tr("Ranger"))
        m.add(tr("Dans une autre série…"), lambda: self._move_to_series(paths), menu=ranger)
        if any(self._is_grouped_in_series(p) for p in paths):
            m.add(tr("Sortir de la série"), lambda: self._detach_from_series(paths), menu=ranger)
        if any(self.store.series_override(p) is not None for p in paths):
            m.add(tr("Rétablir le regroupement automatique"),
                  lambda: self._restore_auto_grouping(paths), menu=ranger)
        for act, folder in self._add_folder_actions(ranger, paths).items():
            m.on(act, lambda f=folder: self._move_paths(paths, f))
        # fichier et depannage
        file_actions = []
        if one and not remote:
            file_actions += [(tr("Renommer le fichier…"), lambda: self._rename_tome(paths[0])),
                             (tr(platforms.REVEAL_LABEL), lambda: self._show_in_explorer(paths[0]))]
        if not remote:
            file_actions.append((tr("Recharger les métadonnées") if one
                                 else tr("Recharger les métadonnées ({n})", n=n),
                                 lambda: self._reload_meta(paths)))
        if one and self.covers.error(paths[0]) is not None:
            file_actions.append((tr("Voir l'erreur…"), lambda: self._show_cover_error(paths[0])))
        if file_actions:
            sub = m.submenu(tr("Fichier"))
            for label, fn in file_actions:
                m.add(label, fn, menu=sub)

        if not remote:
            m.extend(self, "volume", paths)
            m.separator()
            if one:
                label = tr("Supprimer le chapitre…") if chapters else tr("Supprimer le tome…")
            else:
                label = tr("Supprimer {count}…", count=count)
            m.add(label, lambda: self._delete_many(paths))
        m.exec(global_pos)

    def _confirm_reset(self, paths, count):
        """Efface la progression apres confirmation (page courante et
        marquage « termine » sont perdus)."""
        text = (tr("Effacer la progression de ce tome ? La page en cours sera oubliée.")
                if len(paths) == 1 else
                tr("Effacer la progression de {count} ? Les pages en cours seront oubliées.",
                   count=count))
        if QMessageBox.question(self, tr("Réinitialiser la progression"), text,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        for p in paths:
            self.store.remove_progress(p)
        self._rebuild_list()

    def _detach_from_series(self, paths):
        for p in paths:
            if self._is_grouped_in_series(p):
                self.store.set_series_override(p, Store.SERIES_DETACHED)
        self.refresh()

    def _restore_auto_grouping(self, paths):
        for p in paths:
            self.store.clear_series_override(p)
        self.refresh()

    def _show_series_menu(self, key, global_pos):
        """Menu d'un dossier de serie (dans la grille ou par « ⋯ » du panneau)."""
        paths = self._series_paths(key)
        if not paths:
            return
        n = len(paths)
        display = self._series_display_name.get(key) or key

        m = ActionMenu(self)
        m.add(tr("Ouvrir la série"), lambda: self._enter_series(key), default=True)
        m.separator()
        if not all(getattr(self._info.get(p), "status", None) == FINISHED for p in paths):
            m.add(tr("Marquer la série comme lue"), lambda: self._mark_series_finished(key))
        m.add(tr("Statistiques de la série"), lambda: self.open_series_stats(key))
        m.separator()
        m.add(tr("Modifier les informations…"), lambda: self._edit_series_info(key))
        m.add(tr("Renommer la série…"), lambda: self._rename_series(key))
        # nature de publication : tomes, chapitres, ou detection automatique
        nature_menu = m.submenu(tr("Publiée en"))
        current_nature = self.store.series_nature(key)
        for nature, label in units.NATURES:
            m.add(tr(label), lambda v=nature: self._set_series_nature(key, v),
                  menu=nature_menu, checked=nature == current_nature)
        if self.tracker is not None and self.tracker.connected():
            m.add(tr("Associer à AniList…"), lambda: self._associate_anilist(key, paths[0]))
        ranger = m.submenu(tr("Ranger"))
        m.add(tr("Fusionner avec une autre série…"), lambda: self._merge_series(key), menu=ranger)
        for act, folder in self._add_folder_actions(ranger, paths).items():
            m.on(act, lambda f=folder: self._move_paths(paths, f))
        if not any(self._is_remote(p) for p in paths):
            m.extend(self, "series", key)
            m.separator()
            chapters = sum(1 for p in paths if units.is_chapter(self._unit_by_path.get(p)))
            m.add(tr("Supprimer la série ({count})…",
                     count=units.count_text(n - chapters, chapters)),
                  lambda: self._delete_many(paths, series_label=display))
        m.exec(global_pos)

    def _set_series_nature(self, key, nature):
        self.store.set_series_nature(key, nature)
        self._rebuild_list()

    def _show_shelf_menu(self, path, global_pos):
        def then_rebuild(fn):
            return lambda: (fn(path), self._rebuild_list())

        m = ActionMenu(self)
        m.add(tr("Ouvrir"), lambda: self.mangaActivated.emit(path), default=True)
        info = self._info.get(path)
        key = info.series_key if info is not None else None
        # le dossier de la serie, comme un double clic sur elle dans la grille
        if key and len(self._series_paths(key)) > 1:
            m.add(tr("Ouvrir la série"), lambda: self._enter_series(key))
        m.add(tr("Masquer de « Continuer la lecture »"),
              then_rebuild(self.store.dismiss_continue))
        # seulement pour un tome entame : « A suivre » propose un tome non
        # commence, qui n'a pas de progression a effacer
        if self.store.get_progress(path) is not None:
            m.add(tr("Réinitialiser la progression"), then_rebuild(self.store.remove_progress))
        m.add(tr("Marquer comme lu"), then_rebuild(self._mark_finished))
        m.exec(global_pos)
