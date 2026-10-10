"""Actions sur les tomes et les series : marquer lu, renommer, supprimer, deplacer, fusionner, saisie manuelle des informations.

Mixin de LibraryWidget : ces methodes partagent l'etat du widget
(self.list, self.store, self._entries...) ; elles sont regroupees ici par
responsabilite pour garder chaque fichier lisible."""

import logging
from pathlib import Path

from PySide6.QtWidgets import QDialog, QInputDialog, QLineEdit, QMessageBox

from beheread import platforms
from beheread.core.library_model import FINISHED, aggregate_series_info
from beheread.core.series import normalize_name
from beheread.infra.archive import Archive
from beheread.ui import theme

# modules extraits (voir chacun) : constantes de rendu, delegates, dialogues et
# taches d'arriere-plan. LibraryWidget (ci-dessous) orchestre le tout.
from beheread.ui.library.constants import ROLE_IS_SERIES, ROLE_PATH, ROLE_SERIES_KEY
from beheread.ui.library.dialogs import EditInfoDialog


class ActionsMixin:
    # ----- gestion manuelle des series et des informations -----
    def _series_choices(self, exclude_key=None):
        """{nom affiche: nom brut} des series a plusieurs tomes. Le nom brut
        (issu des fichiers) est celui a enregistrer comme regroupement force :
        sa cle normalisee est bien celle de la serie, meme si elle a ete
        renommee a l'affichage."""
        choices = {}
        for key, grp in self._group_entries(self._entries).items():
            if len(grp) < 2 or key == exclude_key:
                continue
            raw = self._series_raw_name.get(key, grp[0].series)
            choices[self._series_display_name.get(key, raw)] = raw
        return dict(sorted(choices.items(), key=lambda kv: kv[0].casefold()))

    def _ask_series(self, title, label, exclude_key=None, editable=True):
        choices = self._series_choices(exclude_key)
        if not choices and not editable:
            QMessageBox.information(self, title, "Aucune autre série dans la bibliothèque.")
            return None
        name, ok = QInputDialog.getItem(self, title, label, list(choices), 0, editable)
        name = (name or "").strip()
        if not ok or not name:
            return None
        return choices.get(name, name)

    def _move_to_series(self, paths):
        raw = self._ask_series("Déplacer vers une série",
                               "Série (choisir ou saisir un nouveau nom) :")
        if raw is None:
            return
        for p in paths:
            self.store.set_series_override(p, raw)
        self.refresh()

    def _merge_series(self, key):
        name = self._series_display_name.get(key, key)
        raw = self._ask_series("Fusionner des séries",
                               f"Rattacher tous les tomes de « {name} » à :",
                               exclude_key=key, editable=False)
        if raw is None:
            return
        for p in self._series_paths(key):
            self.store.set_series_override(p, raw)
        self.refresh()

    def _rename_series(self, key):
        current = self._series_display_name.get(key, key)
        name, ok = QInputDialog.getText(
            self, "Renommer la série",
            "Nom affiché (laisser vide pour revenir au nom détecté) :",
            QLineEdit.Normal, current)
        if not ok:
            return
        name = name.strip()
        raw = self._series_raw_name.get(key)
        self.store.set_series_name(key, None if (not name or name == raw) else name)
        self._rebuild_list()

    def _mark_series_finished(self, key):
        for p in self._series_paths(key):
            if getattr(self._info.get(p), "status", None) != FINISHED:
                self._mark_finished(p)
        self._rebuild_list()

    @staticmethod
    def _manual_meta(existing, authors, year):
        data = dict(existing) if existing and not existing.get("not_found") else {}
        data.update({"authors": authors, "published_year": year, "source": "manual"})
        return data

    def _edit_volume_info(self, path):
        e = self._entry_by_path.get(path)
        if e is None:
            return
        meta = self.store.volume_meta(path)
        info = self._info.get(path) or self._entry_info(e)
        c = theme.colors(self.store.ui_pref("theme", "dark"))
        dlg = EditInfoDialog(info.title, info.author, info.year, c, self)
        if dlg.exec() != QDialog.Accepted:
            return
        authors, year = dlg.values()
        self.store.set_volume_meta(path, self._manual_meta(meta, authors, year))
        self._rebuild_list()

    def _edit_series_info(self, key):
        grp = self._group_entries(self._entries).get(key) or []
        name = self._series_display_name.get(key, key)
        infos = [self._info.get(e.path) or self._entry_info(e) for e in grp]
        agg = aggregate_series_info(name, infos)
        c = theme.colors(self.store.ui_pref("theme", "dark"))
        dlg = EditInfoDialog(f"Série « {name} »", agg.author, agg.year, c, self)
        if dlg.exec() != QDialog.Accepted:
            return
        authors, year = dlg.values()
        self.store.set_series_meta(key, self._manual_meta(self.store.series_meta(key), authors, year))
        # l'auteur de la serie s'applique a chacun de ses tomes (qui ont pu
        # recevoir un autre auteur d'une source en ligne) ; leur date propre
        # est conservee
        for e in grp:
            meta = self.store.volume_meta(e.path)
            data = dict(meta) if meta and not meta.get("not_found") else {}
            data.update({"authors": authors, "source": "manual"})
            data.setdefault("published_year", year)
            self.store.set_volume_meta(e.path, data)
        self._rebuild_list()

    # ----- regroupement automatique en serie (detachement par clic droit) -----
    def _is_grouped_in_series(self, path):
        """Vrai si ce tome fait actuellement partie d'une serie a plusieurs
        tomes (et n'est donc pas deja isole ou detache)."""
        e = self._entry_by_path.get(path)
        if not e or e.detached:
            return False
        key = normalize_name(e.series)
        n = sum(1 for x in self._entries
                if not x.detached and normalize_name(x.series) == key)
        return n > 1

    # caracteres interdits dans un nom de fichier sous Windows
    _INVALID_NAME_CHARS = set('<>:"/\\|?*')

    # noms de peripheriques reserves par Windows (insensibles a la casse, avec
    # ou sans extension) : un fichier ne peut pas s'appeler ainsi.
    _RESERVED_NAMES = {"con", "prn", "aux", "nul",
                       *(f"com{i}" for i in range(1, 10)),
                       *(f"lpt{i}" for i in range(1, 10))}

    def _rename_tome(self, path: str):
        """Renomme le vrai fichier sur le disque (l'extension est conservee).
        La progression, les metadonnees, la vignette et les regroupements
        manuels sont indexes par contenu : ils suivent le fichier renomme."""
        p = Path(path)
        old_stem = p.stem
        new_stem, ok = QInputDialog.getText(
            self, "Renommer le fichier",
            "Nouveau nom (sans l'extension) :", QLineEdit.Normal, old_stem)
        if not ok:
            return
        new_stem = new_stem.strip().rstrip(" .")   # Windows interdit un nom finissant par espace/point
        if not new_stem or new_stem == old_stem:
            return
        if (self._INVALID_NAME_CHARS & set(new_stem)) or any(ord(c) < 32 for c in new_stem):
            QMessageBox.warning(
                self, "Nom invalide",
                'Un nom de fichier ne peut pas contenir les caractères :\n'
                '< > : " / \\ | ? *')
            return
        # "CON", "NUL", "COM1"... sont reserves par Windows, meme avec extension
        if new_stem.split(".")[0].lower() in self._RESERVED_NAMES:
            QMessageBox.warning(
                self, "Nom invalide",
                f'« {new_stem} » est un nom réservé par Windows et ne peut pas '
                "être utilisé comme nom de fichier.")
            return

        target = p.with_name(new_stem + p.suffix)
        if target.exists():
            QMessageBox.warning(
                self, "Renommage impossible",
                f'Un fichier nommé « {target.name} » existe déjà dans ce dossier.')
            return

        try:
            p.rename(target)
        except OSError as e:
            QMessageBox.warning(
                self, "Renommage impossible",
                f"Impossible de renommer le fichier :\n\n{e}\n\n"
                "Il est peut-être ouvert dans le lecteur ou une autre application.")
            return

        self.store.note_renamed(str(p), str(target))
        # la vignette en cache (indexee par contenu) reste valide : on la
        # transfere dans le cache memoire vers le nouveau chemin pour eviter un
        # clignotement le temps d'un rechargement.
        self.covers.rename(str(p), str(target))
        self.refresh()

    @staticmethod
    def _show_in_explorer(path: str):
        """Ouvre l'explorateur de fichiers (le Finder sous macOS) avec le
        fichier selectionne."""
        platforms.reveal_in_file_manager(path)

    def _mark_finished(self, path: str):
        prog = self.store.get_progress(path)
        total = prog[1] if prog and prog[1] else None
        if not total:
            try:
                ar = Archive(path)
                total = len(ar)
                ar.close()
            except Exception as e:
                QMessageBox.warning(self, "Erreur",
                                    f"Impossible de lire l'archive :\n{path}\n\n{e}")
                return
        was_finished = bool(prog and prog[2])
        self.store.set_progress(path, max(0, total - 1), total, True)
        if not was_finished:
            self.volumesFinished.emit([path])

    def _mark_unread(self, path: str):
        """Annule le marquage "termine" en conservant la page courante (inverse
        d'un "Marquer comme lu" accidentel, sans perdre sa progression)."""
        prog = self.store.get_progress(path)
        if prog and prog[2]:
            self.store.set_progress(path, prog[0], prog[1], False)

    def _reload_meta(self, paths):
        """Oublie les metadonnees (et l'eventuel repli serie AniList associe)
        pour relancer la cascade ComicInfo/Google Books/AniList a zero -
        utile si une recherche precedente n'a rien trouve, s'est trompee, ou
        a echoue faute de reseau au moment ou elle a ete tentee."""
        for p in paths:
            self.store.remove_volume_meta(p)
            self.meta.forget_failures(p)
            e = self._entry_by_path.get(p)
            if e is not None:
                self.store.remove_series_meta(normalize_name(e.series))
        self._rebuild_list()

    def _delete_many(self, paths, series_label=None):
        """Supprime les fichiers donnes (corbeille du systeme si possible,
        sinon suppression definitive). `series_label` : si fourni, la
        confirmation annonce la suppression de toute une serie."""
        # corbeille du systeme si elle est utilisable (voir
        # beheread.platforms.trash_function), suppression definitive sinon
        send2trash = platforms.trash_function()
        to_trash = send2trash is not None

        verb = "Mettre à la corbeille" if to_trash else "Supprimer définitivement"
        if series_label:
            title = "Mettre à la corbeille" if to_trash else "Supprimer la série"
            names = "\n".join(f"- {Path(p).stem}" for p in paths[:10])
            if len(paths) > 10:
                names += f"\n… et {len(paths) - 10} de plus"
            message = (f"{verb} les {len(paths)} tomes de « {series_label} » ?\n\n{names}")
        elif len(paths) == 1:
            title = "Mettre à la corbeille" if to_trash else "Supprimer le manga"
            message = f"{verb} « {Path(paths[0]).stem} » ?\n\n{paths[0]}"
        else:
            title = "Mettre à la corbeille" if to_trash else "Supprimer des mangas"
            names = "\n".join(f"- {Path(p).stem}" for p in paths[:10])
            if len(paths) > 10:
                names += f"\n… et {len(paths) - 10} de plus"
            message = f"{verb} {len(paths)} mangas ?\n\n{names}"
        if to_trash:
            message += f"\n\nLes fichiers seront envoyés dans {platforms.TRASH_NAME}."
        else:
            message += "\n\nLes fichiers seront supprimés du disque. Cette action est irréversible."

        confirm = QMessageBox.question(self, title, message,
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return

        deleted, errors = [], []
        for p in paths:
            # l'identite par contenu doit lire le fichier encore present : on
            # resout l'empreinte et le chemin de vignette AVANT la suppression,
            # mais on n'oublie les donnees liees (progression, metadonnees...)
            # qu'APRES sa reussite - un echec (fichier verrouille, droits) ne
            # doit rien effacer.
            key = self.store.key_for(p)
            thumb = self.store.thumb_path(p)
            try:
                if to_trash:
                    send2trash(str(Path(p)))
                else:
                    Path(p).unlink()
            except Exception as e:   # send2trash leve ses propres exceptions
                logging.warning("Suppression impossible de %s", p, exc_info=True)
                errors.append(f"{Path(p).name} : {e}")
                continue
            deleted.append(p)
            self.store.forget_content(key, p)
            try:
                if thumb.exists():
                    thumb.unlink()
            except OSError:
                logging.debug("Vignette non supprimee : %s", thumb, exc_info=True)

        if deleted:
            deleted_set = set(deleted)
            self._set_entries([e for e in self._entries if e.path not in deleted_set])
            self.store.save_library_index([e.to_dict() for e in self._entries])
            self.covers.forget(deleted_set)
            self._rebuild_list()
        if errors:
            QMessageBox.warning(self, "Erreur",
                                "Certains fichiers n'ont pas pu être supprimés :\n\n" +
                                "\n".join(errors))

    def _delete_selected(self):
        """Touche Suppr : supprime les tomes selectionnes (confirmation
        obligatoire), ou la serie si seul un dossier de serie est selectionne."""
        items = self.list.selectedItems()
        tomes = [it.data(ROLE_PATH) for it in items if not it.data(ROLE_IS_SERIES)]
        series = [it for it in items if it.data(ROLE_IS_SERIES)]
        if tomes:
            self._delete_many(tomes)
        elif len(series) == 1:
            key = series[0].data(ROLE_SERIES_KEY)
            paths = self._series_paths(key)
            if paths:
                self._delete_many(paths, series_label=self._series_display_name.get(key)
                                  or series[0].text())
