"""Tomes virtuels dans la bibliotheque : chapitres regroupes et lus comme un
seul tome, sans toucher aux fichiers (voir infra/virtual.py).

Mixin de LibraryWidget. Un tome virtuel est une entree de la bibliotheque
comme une autre (serie, numero, progression, couverture) ; ses chapitres y
sont masques comme ceux deja contenus dans un tome possede. Quand le tome
officiel de meme numero arrive, il prend sa place.
"""

from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from beheread.core import units
from beheread.core.models import LibraryEntry
from beheread.core.series import normalize_name
from beheread.i18n import tr, trn
from beheread.infra import mangadex, virtual
from beheread.ui import style, theme
from beheread.ui.library.constants import ROLE_PATH
from beheread.ui.library.dialogs import _dialog_css
from beheread.ui.library.menus import ActionMenu
from beheread.ui.library.workers import CallWorker
from beheread.ui.safe_text import plain


def _hint(text):
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def _buttons(dialog, ok_text):
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = QPushButton(tr("Annuler"))
    cancel.clicked.connect(dialog.reject)
    ok = QPushButton(ok_text)
    ok.setObjectName("primary")
    ok.setDefault(True)
    ok.clicked.connect(dialog.accept)
    row.addWidget(cancel)
    row.addWidget(ok)
    return row, ok


class VirtualVolumeDialog(QDialog):
    """« Regrouper en tome » : numero du tome virtuel (cree ou modifie)."""

    def __init__(self, series_name, chapters_text, number, colors, editing=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Tome virtuel") if editing else tr("Regrouper en tome"))
        self.setMinimumWidth(460)
        self.setStyleSheet(_dialog_css(colors))
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)
        heading = QLabel(tr("Tome virtuel") if editing else tr("Regrouper en tome"))
        heading.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(heading)
        intro = QLabel(f"{series_name} · {chapters_text}")
        intro.setTextFormat(Qt.PlainText)   # nom de serie : non fiable
        intro.setWordWrap(True)
        root.addWidget(intro)
        root.addWidget(_hint(tr("Les fichiers ne sont pas modifiés : le tome se lit d'une "
                                "traite et se dissocie à tout moment. Il est remplacé par le "
                                "tome officiel de même numéro dès que celui-ci arrive.")))
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Numéro")))
        self.number = QSpinBox()
        self.number.setRange(1, 9999)
        self.number.setValue(int(number))
        self.number.setAccessibleName(tr("Numéro"))
        row.addWidget(self.number)
        row.addStretch(1)
        root.addLayout(row)
        root.addWidget(_hint(tr("Couverture : la première page du premier chapitre. Pour en "
                                "choisir une autre : clic droit sur le tome › « Choisir la "
                                "couverture… ».")))
        buttons, _ok = _buttons(self, tr("Enregistrer") if editing else tr("Créer le tome"))
        root.addLayout(buttons)


class ChapterPickerDialog(QDialog):
    """« Ajouter ou retirer des chapitres » d'un tome virtuel : liste a
    cocher des chapitres disponibles de la serie."""

    def __init__(self, title, choices, colors, parent=None):
        """`choices` : [(libelle, chemin, coche)]."""
        super().__init__(parent)
        self.setWindowTitle(tr("Chapitres du tome"))
        self.setMinimumSize(420, 460)
        self.setStyleSheet(_dialog_css(colors) + f"""
            QListWidget {{ background: {colors['panel']}; color: {colors['text']};
                           border: 1px solid {colors['border']}; border-radius: 6px; }}""")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        heading = QLabel(title)
        heading.setTextFormat(Qt.PlainText)
        heading.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(heading)
        root.addWidget(_hint(tr("Cochez les chapitres qui composent ce tome.")))
        self.list = QListWidget()
        for label, path, checked in choices:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, path)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self.list.addItem(item)
        root.addWidget(self.list, 1)
        buttons, self.ok = _buttons(self, tr("Enregistrer"))
        root.addLayout(buttons)
        self.list.itemChanged.connect(lambda _item: self.ok.setEnabled(bool(self.checked())))

    def checked(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


class VirtualMixin:
    # ------------------------------------------------------------ entrees
    def _virtual_entries(self, file_entries):
        """Entrees des tomes virtuels d'apres leur definition (Store) et les
        chapitres presents. Met a jour le registre des chapitres (Archive),
        les chapitres regroupes (masques, voir _compute_units) et les tomes
        virtuels dont le tome officiel est arrive (_superseded)."""
        self._grouped_chapters = set()
        self._virtual_members = {}
        self._superseded = []
        defs = self.store.virtual_volumes()
        if not defs:
            virtual.registry.set_all({})
            return []
        wanted = {d.get("series") for d in defs.values()}
        by_key = {}         # empreinte de contenu -> entree (chapitres candidats)
        real_volumes = set()   # (serie, numero) des tomes reels
        for e in file_entries:
            if e.detached:
                continue
            key = normalize_name(e.series)
            if key not in wanted:
                continue
            by_key[self.store.key_for(e.path)] = e
            if e.kind in ("volume", "bare") and e.volume is not None:
                real_volumes.add((key, e.volume))
        found = []
        for vid, d in defs.items():
            members = [by_key[k] for k in d.get("chapters") or () if k in by_key]
            number = d.get("number")
            if not members or not isinstance(number, int):
                continue
            series_key = d.get("series")
            path = virtual.make_path(vid, d.get("name") or members[0].series, number)
            self._grouped_chapters.update(m.path for m in members)
            if (series_key, number) in real_volumes:
                # le tome officiel est la : proposition de remplacement
                self._superseded.append((vid, d, path, members))
                continue
            self._virtual_members[path] = members
            found.append(LibraryEntry(
                path=path, title=Path(path).stem, series=members[0].series, volume=number,
                kind="volume", added=max(m.added for m in members)))
        virtual.registry.set_all({p: [m.path for m in ms]
                                  for p, ms in self._virtual_members.items()})
        if self._superseded:
            QTimer.singleShot(0, self._offer_replacements)
        return found

    def _refresh_virtual(self):
        """Definition d'un tome virtuel modifiee : entrees et grille a jour."""
        self._set_entries(self._file_entries)
        self._rebuild_list()

    # ------------------------------------------------------------ barre de selection
    def _build_group_bar(self):
        """Barre flottante au bas de la grille quand plusieurs chapitres d'une
        serie ouverte sont selectionnes : « 10 chapitres selectionnes ·
        Regrouper en tome… »."""
        # posee sur la zone visible (la grille, elle, deborde sous l'en-tete)
        bar = QFrame(self.list_host)
        bar.setObjectName("groupBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 8, 10, 8)
        row.setSpacing(12)
        self._group_bar_text = QLabel()
        self._group_bar_text.setTextFormat(Qt.PlainText)
        row.addWidget(self._group_bar_text)
        group = QPushButton(tr("Regrouper en tome…"))
        group.setObjectName("primary")
        group.clicked.connect(
            lambda: self._group_chapters([it.data(ROLE_PATH) for it in self.list.selectedItems()]))
        row.addWidget(group)
        cancel = QPushButton(tr("Annuler"))
        cancel.clicked.connect(self.list.clearSelection)
        row.addWidget(cancel)
        bar.hide()
        self._group_bar = bar
        self.list.itemSelectionChanged.connect(self._update_group_bar)

    def _selected_chapters(self):
        if self._current_series is None:
            return []
        entries = [self._entry_by_path.get(it.data(ROLE_PATH)) for it in self.list.selectedItems()]
        if len(entries) < 2 or any(e is None or self._unit(e) != units.CHAPTER for e in entries):
            return []
        return entries

    def _update_group_bar(self):
        bar = self._group_bar
        chapters = self._selected_chapters()
        if not chapters:
            bar.hide()
            return
        text = trn(len(chapters), "{n} chapitre sélectionné", "{n} chapitres sélectionnés")
        numbers = [e.volume for e in chapters if e.volume is not None]
        if numbers:
            text += " · " + units.chapter_range_text(min(numbers), max(numbers))
        self._group_bar_text.setText(text)
        c = theme.colors(self.store.ui_pref("theme", "dark"))
        bar.setStyleSheet(f"""
            #groupBar {{ background: {c['button']}; border: 1px solid {c['border']};
                         border-radius: 8px; }}
            QLabel {{ color: {c['text']}; font-size: 14px; }}
            QPushButton {{ color: {c['text']}; background: transparent;
                           border: 1px solid {c['border']}; border-radius: 6px; padding: 6px 14px; }}
            """ + style.primary_button("QPushButton#primary"))
        bar.adjustSize()
        area = self.list_host.rect()
        bar.move(area.center().x() - bar.width() // 2, area.bottom() - bar.height() - 20)
        bar.show()
        bar.raise_()

    # ------------------------------------------------------------ creation
    def _chapter_label(self, e):
        return units.chapter_range_text(e.volume, e.volume) if e.volume is not None \
            else self._display_title(e)

    def _members_text(self, members):
        numbers = [m.volume for m in members if m.volume is not None]
        n = len(members)
        text = trn(n, "{n} chapitre", "{n} chapitres")
        if numbers:
            text += " (" + units.chapter_range_text(min(numbers), max(numbers)) + ")"
        return text

    def _next_volume_number(self, key):
        grp = self._group_entries(self._entries).get(key) or []
        numbers = [int(e.volume) for e in grp
                   if self._unit(e) == units.VOLUME and e.volume is not None]
        return max(numbers, default=0) + 1

    def _group_chapters(self, paths):
        """« Regrouper en tome… » sur des chapitres d'une meme serie."""
        members = [self._entry_by_path[p] for p in paths if p in self._entry_by_path]
        members = [m for m in members if self._unit(m) == units.CHAPTER]
        if len(members) < 2:
            return
        key = normalize_name(members[0].series)
        if any(normalize_name(m.series) != key for m in members):
            return
        members.sort(key=self._volume_sort_key)
        name = self._series_display_name.get(key, members[0].series)
        dialog = VirtualVolumeDialog(name, self._members_text(members),
                                     self._next_volume_number(key),
                                     theme.colors(self.store.ui_pref("theme", "dark")),
                                     parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._create_virtual(key, members, dialog.number.value())

    def _create_virtual(self, key, members, number, refresh=True):
        """Cree le tome virtuel et reprend la lecture deja faite de ses
        chapitres (termine s'ils le sont tous, sinon au premier non termine)."""
        vid = virtual.new_id()
        name = self._series_raw_name.get(key, members[0].series)
        self.store.set_virtual_volume(vid, {
            "series": key, "name": name, "number": int(number),
            "chapters": [self.store.key_for(m.path) for m in members]})
        path = virtual.make_path(vid, name, int(number))
        self._carry_chapters_progress(path, [m.path for m in members])
        self.store.flush()
        if refresh:
            self._refresh_virtual()
        return path

    def _carry_chapters_progress(self, path, chapter_paths):
        done = [bool((self.store.get_progress(p) or (0, 0, False))[2]) for p in chapter_paths]
        if not any(done):
            return
        try:
            ar = virtual.VirtualArchive(path, chapter_paths)
        except Exception:
            return
        total, spans = len(ar), ar.spans
        ar.close()
        if all(done):
            self.store.set_progress(path, max(0, total - 1), total, True)
            return
        first_unread = next(first for (first, _last, _p), d in zip(spans, done, strict=True)
                            if not d)
        if first_unread:
            self.store.set_progress(path, first_unread, total, False)

    # ------------------------------------------------------------ proposition MangaDex
    def _complete_volumes(self, key, grp):
        """[(numero, chapitres)] des tomes officiels dont tous les chapitres
        sont presents en chapitres libres (decoupage MangaDex), sans tome
        reel ni virtuel de ce numero, et que l'utilisateur n'a pas dissocies."""
        ranges = self.store.chapter_ranges(key)
        if not ranges:
            return []
        volumes = {int(e.volume) for e in grp
                   if self._unit(e) == units.VOLUME and e.volume is not None}
        dismissed = self.store.virtual_dismissed(key)
        chapters = [e for e in grp if self._unit(e) == units.CHAPTER and e.volume is not None]
        found = []
        for name, span in ranges.items():
            try:
                number = int(float(name))
            except (TypeError, ValueError):
                continue
            if number in volumes or number in dismissed or len(span) != 2:
                continue
            first, last = span
            members = [e for e in chapters if first <= e.volume <= last]
            owned = {int(e.volume) for e in members if float(e.volume).is_integer()}
            if members and all(n in owned for n in range(int(first), int(last) + 1)):
                found.append((number, sorted(members, key=self._volume_sort_key)))
        return sorted(found, key=lambda f: f[0])

    def _auto_virtual_volumes(self):
        """Tous les chapitres d'un tome officiel sont la : le tome virtuel
        est cree tout seul, avec sa couverture officielle (en ligne)."""
        created = False
        for key, grp in self._group_entries(self._entries).items():
            if not any(self._unit(e) == units.CHAPTER for e in grp):
                continue
            for number, members in self._complete_volumes(key, grp):
                path = self._create_virtual(key, members, number, refresh=False)
                self._fetch_official_cover(path, key, number)
                created = True
        if created:
            self._refresh_virtual()

    # ------------------------------------------------------------ menu d'un tome virtuel
    def _show_virtual_menu(self, path, global_pos):
        m = ActionMenu(self)
        m.add(tr("Ouvrir"), lambda: self.mangaActivated.emit(path), default=True)
        m.separator()
        if (self.store.get_progress(path) or (0, 0, False))[2]:
            m.add(tr("Marquer comme non lu"),
                  lambda: (self._mark_unread(path), self._rebuild_list()))
        else:
            m.add(tr("Marquer comme lu"),
                  lambda: (self._mark_finished(path), self._rebuild_list()))
        m.separator()
        m.add(tr("Ajouter ou retirer des chapitres…"), lambda: self._edit_virtual_chapters(path))
        m.add(tr("Changer le numéro…"), lambda: self._renumber_virtual(path))
        m.add(tr("Choisir la couverture…"), lambda: self._choose_cover(path))
        m.separator()
        m.add(tr("Dissocier (garder les chapitres)"), lambda: self._dissolve_virtual(path))
        m.exec(global_pos)

    # ------------------------------------------------------------ couverture officielle
    def _official_fetcher(self, key, number):
        """Fonction (hors thread UI) qui renvoie l'image de la couverture
        officielle du tome `number` de la serie (MangaDex), ou b""."""
        manga_id = ((self.store.chapter_map(key) or {}).get("id")
                    or (self.store.series_meta(key) or {}).get("mangadex_id"))
        name = self._series_raw_name.get(key, key)

        def fetch():
            mid = manga_id or (mangadex.search_series(name) or {}).get("mangadex_id")
            return mangadex.volume_cover(mid, number) if mid else b""
        return fetch

    def _official_cover_option(self, path):
        """(fetch, source) de la couverture officielle a proposer dans
        « Choisir la couverture… », ou None : tome virtuel, ou tome ordinaire
        numerote d'une serie (pas un chapitre, ni une edition au decoupage
        different dont les numeros ne sont pas ceux de MangaDex) ; recherche
        en ligne autorisee."""
        if not self._online_meta():
            return None
        if virtual.is_virtual(path):
            _vid, d = self._virtual_def(path)
            key, number = (d.get("series"), d.get("number")) if d else (None, None)
        else:
            e = self._entry_by_path.get(path)
            if (e is None or e.detached or self._unit(e) != units.VOLUME
                    or e.volume is None or not float(e.volume).is_integer()):
                return None
            key, number = normalize_name(e.series), int(e.volume)
            if self._series_edition(key):
                return None
        if not key or not isinstance(number, int):
            return None
        return (self._official_fetcher(key, number), tr("Tome {n} · MangaDex", n=number))

    def _fetch_official_cover(self, path, key, number, quiet=True):
        """Couverture officielle du tome `number` de la serie (MangaDex, en
        arriere-plan), qui devient la couverture choisie du tome virtuel
        `path`. `quiet` : sans message si MangaDex n'en a pas (creation
        automatique)."""
        if not self._online_meta() or path in self._cover_calls:
            return
        call = CallWorker(self._official_fetcher(key, number))
        call.signals.done.connect(
            lambda data, err: self._on_official_cover(path, number, data, err, quiet))
        self._cover_calls[path] = call   # garde une reference (sinon GC)
        QThreadPool.globalInstance().start(call)

    def _on_official_cover(self, path, number, data, err, quiet):
        self._cover_calls.pop(path, None)
        image = QImage.fromData(data) if data else QImage()
        if image.isNull():
            if not quiet:
                QMessageBox.information(
                    self, tr("Couverture officielle"),
                    plain(str(err)) if err is not None
                    else tr("MangaDex n'a pas de couverture pour le tome {n}.", n=number))
            return
        if path not in self._entry_by_path:
            return   # tome dissocie ou renumerote entre-temps
        try:
            self.store.set_custom_cover(path, image=image)
        except OSError as e:
            if not quiet:
                QMessageBox.warning(self, tr("Couverture non enregistrée"), plain(e))
            return
        self.covers.forget([path])
        self.covers.request(path)
        self.list.viewport().update()

    def _virtual_def(self, path):
        vid = virtual.volume_id(path)
        return vid, self.store.virtual_volumes().get(vid)

    def _edit_virtual_chapters(self, path):
        vid, d = self._virtual_def(path)
        members = self._virtual_members.get(path) or []
        if d is None or not members:
            return
        key = d.get("series")
        current = {m.path for m in members}
        grp = self._group_entries(self._entries).get(key) or []
        candidates = [e for e in grp if e.path in current or self._unit(e) == units.CHAPTER]
        candidates.sort(key=self._volume_sort_key)
        choices = [(self._chapter_label(e), e.path, e.path in current) for e in candidates]
        dialog = ChapterPickerDialog(self._display_title(self._entry_by_path[path]), choices,
                                     theme.colors(self.store.ui_pref("theme", "dark")), self)
        if dialog.exec() != QDialog.Accepted or not dialog.checked():
            return
        d = dict(d, chapters=[self.store.key_for(p) for p in dialog.checked()])
        self.store.set_virtual_volume(vid, d)
        self.store.set_custom_cover(path)   # vignette regeneree (premier chapitre)
        self.covers.forget([path])
        self.store.flush()
        self._refresh_virtual()

    def _renumber_virtual(self, path):
        vid, d = self._virtual_def(path)
        members = self._virtual_members.get(path) or []
        if d is None:
            return
        key = d.get("series")
        name = self._series_display_name.get(key, d.get("name", ""))
        dialog = VirtualVolumeDialog(name, self._members_text(members), d.get("number", 1),
                                     theme.colors(self.store.ui_pref("theme", "dark")),
                                     editing=True, parent=self)
        if dialog.exec() != QDialog.Accepted or dialog.number.value() == d.get("number"):
            return
        number = dialog.number.value()
        new_path = virtual.make_path(vid, d.get("name") or name, number)
        self._move_virtual_state(path, new_path)
        self.store.set_virtual_volume(vid, dict(d, number=number))
        self.store.flush()
        self._refresh_virtual()

    def _move_virtual_state(self, old, new):
        """Le chemin d'un tome virtuel porte son numero : sa progression, sa
        couverture choisie et son nombre de pages suivent le changement."""
        prog = self.store.get_progress(old)
        if prog is not None:
            self.store.set_progress(new, *prog)
            self.store.remove_progress(old)
        pages = self.store.page_count(old)
        if pages:
            self.store.set_page_count(new, pages)
        cover = self.store.custom_cover(old)
        if cover and cover.get("page"):
            self.store.set_custom_cover(new, page=cover["page"])
        elif cover and cover.get("image"):
            from PySide6.QtGui import QImage
            image = QImage(cover["image"])
            if not image.isNull():
                self.store.set_custom_cover(new, image=image)
        if cover:
            self.store.set_custom_cover(old)
        self.covers.forget([old])

    def _dissolve_virtual(self, path):
        vid, d = self._virtual_def(path)
        if d is None:
            return
        # dissocie a la main : il n'est plus recree automatiquement
        if isinstance(d.get("number"), int):
            self.store.dismiss_virtual(d.get("series"), d["number"])
        self.store.remove_virtual_volume(vid)
        self.store.remove_progress(path)
        self.store.set_custom_cover(path)
        self.covers.forget([path])
        self.store.flush()
        self._refresh_virtual()

    # ------------------------------------------------------------ arrivee du tome officiel
    def _offer_replacements(self):
        """Le tome officiel d'un tome virtuel est arrive : il le remplace (la
        lecture est reprise), ses chapitres sont desormais « deja inclus dans
        les tomes » ; l'utilisateur choisit de garder leurs fichiers ou de les
        mettre a la corbeille. Proposee une fois par tome et par session."""
        offered = self._replacements_offered
        pending = [s for s in self._superseded if s[0] not in offered]
        if not pending:
            return
        for vid, d, path, members in pending:
            offered.add(vid)
            key, number = d.get("series"), d.get("number")
            grp = self._group_entries(self._entries).get(key) or []
            official = next((e for e in grp if self._unit(e) == units.VOLUME
                             and e.volume == number and not virtual.is_virtual(e.path)), None)
            if official is None:
                continue
            name = self._series_display_name.get(key, d.get("name", ""))
            numbers = [m.volume for m in members if m.volume is not None]
            done = (self.store.get_progress(path) or (0, 0, False))[2] or all(
                (self.store.get_progress(m.path) or (0, 0, False))[2] for m in members)
            box = QMessageBox(self)
            box.setWindowTitle(tr("Tome officiel arrivé"))
            box.setText(plain(tr("Le tome {n} de « {series} » est arrivé.", n=number,
                                 series=name)))
            info = tr("Il remplace le tome virtuel ({chapters}).",
                      chapters=self._members_text(members))
            if done:
                info += " " + tr("Votre lecture est conservée : tome {n} lu.", n=number)
            info += "\n\n" + trn(len(members),
                                 "Le fichier du chapitre est maintenant inclus dans le tome et "
                                 "sera masqué.",
                                 "Les {n} fichiers de chapitres sont maintenant inclus dans le "
                                 "tome et seront masqués.")
            box.setInformativeText(plain(info))
            keep = box.addButton(tr("Garder les fichiers"), QMessageBox.RejectRole)
            trash = box.addButton(tr("Mettre les chapitres à la corbeille"),
                                  QMessageBox.AcceptRole)
            box.setDefaultButton(keep)
            box.exec()
            if numbers:
                self.store.set_manual_chapter_range(key, str(number),
                                                    [min(numbers), max(numbers)])
            if done and not (self.store.get_progress(official.path) or (0, 0, False))[2]:
                self._mark_finished(official.path)
            self.store.remove_virtual_volume(vid)
            self.store.remove_progress(path)
            self.store.flush()
            if box.clickedButton() == trash:
                self._delete_many([m.path for m in members], confirm=False)
        self._refresh_virtual()

