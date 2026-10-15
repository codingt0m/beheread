"""Seance de lecture : rythme et temps restant, sauvegarde de la progression, statistiques, fermeture.

Mixin de ReaderWidget : ces methodes partagent l'etat du lecteur
(self.page, self.cache, self.store...) ; elles sont regroupees ici par
responsabilite."""

import time

from beheread.core.library_model import is_started
from beheread.core.series import parse_path
from beheread.i18n import tr
from beheread.infra import servers
from beheread.infra.storage import Store
from beheread.ui.reader.constants import TIME_MIN_SAMPLES


class SessionMixin:
    def _save_progress(self, finished=None):
        prev = self.store.get_progress(self.path)
        if finished is None:
            last = max(self._current_indices())
            finished = last >= self.total - 1
            if prev and prev[2]:
                finished = True  # ne pas "determiner" un manga deja fini
        self.store.set_progress(self.path, self.page, self.total, finished)
        if finished and not (prev and prev[2]):
            # fin de tome journalisee sur-le-champ (et non a la fermeture) :
            # elle est datee du bon jour et survit a un arret brutal
            self.store.record_reading(self.path, 0, 0, True, servers.display_name(self.path),
                                      self._series_label())
            self.volume_finished.emit(self.path)

    # ------------------------------------------------------------ mesure de la seance
    def _now(self):
        """Horloge de la seance (remplacee dans les tests)."""
        return time.monotonic()

    def _on_last_view(self):
        return max(self._current_indices()) >= self.total - 1

    def _active_seconds(self):
        return self._meter.active_seconds

    def _time_remaining_text(self):
        pace = self._meter.pace(TIME_MIN_SAMPLES)
        if pace is None:
            return ""
        remaining_pages = max(0, (self.total - 1) - self.page)
        if remaining_pages <= 0:
            return ""
        minutes = pace * remaining_pages / 60.0
        if minutes < 1:
            return tr("moins d'une minute restante")
        return tr("~{minutes} min restantes", minutes=int(round(minutes)))

    @staticmethod
    def _fmt_duration(seconds):
        seconds = int(seconds)
        if seconds < 60:
            return f"{seconds} s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} min"
        return f"{minutes // 60} h {minutes % 60:02d}"

    # ------------------------------------------------------------ fermeture
    def close_reader(self):
        self.release()
        self.closed.emit()

    def release(self):
        """Sauvegarde la progression et la seance (journal de lecture, d'ou
        vient aussi le rythme de lecture), puis ferme l'archive. Idempotent :
        appele a la fermeture du lecteur ET quand il est remplace par le tome
        suivant (voir MainWindow.open_manga) - sans quoi la seance d'un tome
        enchaine etait perdue."""
        if self._released:
            return
        self._released = True
        self._chrome_timer.stop()
        # la vue en cours n'est comptee comme lue que si le tome est fini
        self._meter.leave(self._now(), self._current_indices(),
                          forward=self._on_last_view(), resume=False)
        self._save_progress()
        self._forget_barely_started()
        self._record_session()
        self.pages.shutdown()
        self.archive.close()
        self.session_ended.emit(self.path)

    def _forget_barely_started(self):
        """Tome referme sur l'une de ses premieres pages (couverture, page de
        garde) : il n'est pas commence, sa progression est effacee - il ne
        s'affiche ni « en cours » ni dans « Continuer la lecture ». Un tome
        deja termine le reste. Le temps passe, lui, reste aux statistiques."""
        prog = self.store.get_progress(self.path)
        if prog and not prog[2] and not is_started(self.page):
            self.store.remove_progress(self.path)

    def _record_session(self):
        """Ajoute la seance au journal des statistiques : pages lues et temps
        actif (voir core/reading_session.py). La fin du tome, elle, est
        journalisee des qu'elle survient (voir _save_progress)."""
        self.store.record_reading(self.path, len(self._meter.pages), self._meter.active_seconds,
                                  False, servers.display_name(self.path), self._series_label())

    def _series_label(self):
        """Nom de serie pour les statistiques (regroupement manuel prioritaire)."""
        e = self.entry
        if e is not None:   # meme deduction, deja faite par la bibliotheque
            return e.series if e.manual or e.volume is not None else servers.display_name(self.path)
        override = self.store.series_override(self.path)
        if override and override != Store.SERIES_DETACHED:
            return override
        name, volume, _kind = parse_path(self.path)
        return name if volume is not None else servers.display_name(self.path)

    def leave_direct_mode(self):
        """L'application, lancee sur un fichier, est rouverte normalement
        (instance unique) : la fermeture du lecteur ramenera desormais a la
        bibliotheque au lieu de quitter. Met a jour les libelles en consequence."""
        if not self.direct_mode:
            return
        self.direct_mode = False
        self.back_button.setText(" " + tr("Bibliothèque"))
        self.back_button.setAccessibleName(tr("Retour à la bibliothèque"))
        self.back_button.adjustSize()
        self.end_lib_btn.setText(tr("Bibliothèque"))
        self._place_corner_buttons()
