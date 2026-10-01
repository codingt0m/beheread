"""Beheread - lecteur de mangas CBZ / CBR / EPUB / PDF pour Windows 10/11.
Lecture et donnees 100% locales ; seule la recuperation des metadonnees
(auteur, date) interroge des API publiques (voir metadata.py).

Lancement :  python main.py
Voir README.md pour l'installation et le support des fichiers CBR.
"""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from beheread.infra import applogging
from beheread.infra.archive import ArchiveError
from beheread.infra.database import DatabaseTooNew
from beheread.infra.hotkey import GlobalHotkey
from beheread.infra.single_instance import SingleInstance, send_to_primary
from beheread.infra.storage import Store, data_dir
from beheread.services.anilist_tracker import AniListTracker
from beheread.ui import appicon, theme
from beheread.ui.library.widget import LibraryWidget
from beheread.ui.reader.widget import ReaderWidget
from beheread.version import __version__

APP_NAME = "Beheread"


class ReaderWindow(QMainWindow):
    """Fenetre independante pour le lecteur : s'ouvre par-dessus la
    bibliotheque (masquee pendant ce temps), en fenetre maximisee - pas en
    plein ecran OS tant que l'utilisateur ne le demande pas explicitement."""

    def __init__(self):
        super().__init__()
        self.setWindowIcon(appicon.app_icon())
        QShortcut(QKeySequence(Qt.Key_F11), self, self.toggle_fullscreen)

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def closeEvent(self, event):
        reader = self.centralWidget()
        if reader is not None:
            reader.close_reader()  # sauvegarde la progression, previent MainWindow
        super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(appicon.app_icon())
        self.resize(1200, 800)   # taille de repli si l'utilisateur desmaximise

        self.library = LibraryWidget(self.store)
        self.library.mangaActivated.connect(self.open_manga)
        self.library.preferencesChanged.connect(self.apply_preferences)

        # suivi AniList
        self.tracker = AniListTracker(store, self.library.series_volumes_for, self)
        self.library.set_services(tracker=self.tracker)
        self.library.volumesFinished.connect(self.tracker.on_volumes_finished)
        QTimer.singleShot(3000, self.tracker.flush_pending)   # envois restes en attente
        self.setCentralWidget(self.library)

        self.reader = None
        self.reader_window = None
        # mode "lecture directe" : l'app a ete lancee sur un fichier (double-clic
        # dans l'explorateur). On n'affiche jamais la bibliotheque et on quitte
        # quand le lecteur se ferme, au lieu de revenir a la bibliotheque.
        self.direct_mode = False

        QShortcut(QKeySequence(Qt.Key_F11), self, self.toggle_fullscreen)

        # touche "boss" : Ctrl+Alt+C masque/reaffiche la fenetre courante
        # depuis n'importe ou (raccourci global Windows). Voir aussi la
        # touche "c" du lecteur qui ne fait que masquer.
        # (desactivable dans les preferences)
        self._boss_hotkey = None
        self._sync_global_hotkey()
        QApplication.instance().aboutToQuit.connect(
            lambda: self._boss_hotkey is not None and self._boss_hotkey.unregister())

    def open_file_directly(self, path: str):
        """Lance l'app directement sur un fichier (double-clic dans
        l'explorateur) : on ouvre le lecteur sans jamais montrer la
        bibliotheque. La fermeture du lecteur quitte l'application."""
        self.direct_mode = True
        self.open_manga(path)

    def open_manga(self, path: str):
        try:
            reader = ReaderWidget(path, self.store, direct_mode=self.direct_mode)
        except ArchiveError as e:
            logging.warning("Ouverture impossible (%s): %s", path, e)
            QMessageBox.warning(self, "Impossible d'ouvrir le manga", str(e))
            self._on_open_failed()
            return
        except Exception as e:
            logging.exception("Erreur inattendue a l'ouverture de %s", path)
            QMessageBox.warning(self, "Erreur", f"{path}\n\n{e}")
            self._on_open_failed()
            return

        old_reader = self.reader
        self.reader = reader
        reader.closed.connect(self.close_reader)
        reader.next_volume_requested.connect(self.open_manga)
        reader.session_ended.connect(self.tracker.on_session_end)

        first_open = self.reader_window is None
        if first_open:
            self.reader_window = ReaderWindow()
        win = self.reader_window
        reader.fullscreen_toggled.connect(win.toggle_fullscreen)
        win.setCentralWidget(reader)   # avant showMaximized : la fenetre a deja
        win.setWindowTitle(f"{Path(path).stem}  —  {APP_NAME}")  # son contenu au premier affichage
        if first_open:
            win.showMaximized()
            self.hide()   # la bibliotheque passe derriere, comme un popup
        win.activateWindow()
        win.raise_()
        # activateWindow() est asynchrone (surtout a la toute premiere ouverture,
        # pendant que la bibliotheque se masque) : un setFocus() immediat peut
        # ne pas "tenir" une fois la fenetre reellement activee par l'OS. On le
        # redemande apres la boucle d'evenements pour que les fleches marchent
        # sans avoir a cliquer d'abord dans la fenetre.
        QTimer.singleShot(0, reader.setFocus)

        if old_reader is not None:
            # enchainement direct sur le tome suivant : on remplace le lecteur
            # dans la meme fenetre, sans repasser par la bibliotheque.
            # release() sauvegarde aussi le rythme de lecture mesure sur ce tome.
            old_reader.release()
            old_reader.deleteLater()

    def _on_open_failed(self):
        """Le fichier passe en ligne de commande n'a pas pu s'ouvrir. En mode
        direct il n'y a pas de bibliotheque de repli : on quitte l'app - sauf
        si un autre tome est deja ouvert (fichier transmis par une seconde
        instance), qu'on garde alors a l'ecran."""
        if self.direct_mode and self.reader is None:
            QApplication.instance().quit()

    def handle_instance_message(self, msg: dict):
        """Demande d'une instance lancee apres celle-ci (voir
        single_instance.py) : ouvrir un fichier (double-clic dans
        l'explorateur) ou simplement revenir au premier plan (application
        relancee depuis le menu Demarrer)."""
        path = msg.get("open")
        if path:
            self.open_manga(path)
        elif self.direct_mode and self.reader is not None:
            # l'utilisateur a lance l'application normalement : fermer le
            # lecteur ramenera desormais a la bibliotheque au lieu de quitter
            self.direct_mode = False
            self.reader.leave_direct_mode()
        self._bring_to_front()

    def _bring_to_front(self):
        win = self.reader_window if self.reader_window is not None else self
        if win.windowState() & Qt.WindowMinimized:
            win.setWindowState(win.windowState() & ~Qt.WindowMinimized)
        if not win.isVisible():
            win.showMaximized()
        win.show()
        win.raise_()
        win.activateWindow()

    def close_reader(self):
        if self.reader_window is not None:
            win = self.reader_window
            self.reader_window = None
            self.reader = None
            win.hide()
            win.deleteLater()
            if self.direct_mode:
                # lance sur un fichier : pas de bibliotheque a reafficher
                QApplication.instance().quit()
                return
            self.library.update_progress_display()
            self.showMaximized()
            self.activateWindow()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def toggle_boss(self):
        """Reduit (masque de l'ecran, garde dans la barre des taches) ou
        restaure la fenetre actuellement a l'ecran : le lecteur s'il est
        ouvert, sinon la bibliotheque. Preserve l'etat maximise/plein ecran."""
        win = self.reader_window if self.reader_window is not None else self
        if win.windowState() & Qt.WindowMinimized:
            win.setWindowState(win.windowState() & ~Qt.WindowMinimized)
            win.show()
            win.activateWindow()
            win.raise_()
        else:
            win.showMinimized()

    def _apply_current_theme(self):
        apply_theme(QApplication.instance(), self.store.ui_pref("theme", "dark"),
                    self.store.ui_pref("accent"))
        for win in (self, self.reader_window):
            if win is not None:
                win.setWindowIcon(appicon.app_icon())
        self.library.apply_theme()
        if self.reader is not None:
            self.reader.apply_theme()

    def apply_preferences(self):
        """Preferences enregistrees depuis la bibliotheque : applique ce qui
        releve de la fenetre principale (theme, couleur d'accentuation,
        raccourci global)."""
        self._apply_current_theme()
        self._sync_global_hotkey()

    def _sync_global_hotkey(self):
        """Enregistre ou libere le raccourci global Ctrl+Alt+C selon la
        preference (RegisterHotKey est exclusif : le liberer le rend aux
        autres applications)."""
        want = bool(self.store.ui_pref("global_hotkey", True))
        app = QApplication.instance()
        if want and self._boss_hotkey is None:
            self._boss_hotkey = GlobalHotkey(self.toggle_boss)
            app.installNativeEventFilter(self._boss_hotkey)
        elif not want and self._boss_hotkey is not None:
            self._boss_hotkey.unregister()
            app.removeNativeEventFilter(self._boss_hotkey)
            self._boss_hotkey = None

    def closeEvent(self, event):
        if self.reader is not None:
            self.reader.close_reader()
        self.store.flush()   # garantit l'ecriture des dernieres modifications differees
        super().closeEvent(event)


def apply_theme(app: QApplication, mode: str, accent=None):
    """Applique le theme clair/sombre et la couleur d'accentuation (None =
    accent par defaut) a toute l'application."""
    theme.set_accent(accent, mode)
    app.setWindowIcon(appicon.app_icon())
    app.setStyle("Fusion")
    c = theme.colors(mode)
    p = QPalette()
    p.setColor(QPalette.Window, QColor(c["window"]))
    p.setColor(QPalette.WindowText, QColor(c["text"]))
    p.setColor(QPalette.Base, QColor(c["panel"]))
    p.setColor(QPalette.AlternateBase, QColor(c["window"]))
    p.setColor(QPalette.Text, QColor(c["text"]))
    p.setColor(QPalette.Button, QColor(c["button"]))
    p.setColor(QPalette.ButtonText, QColor(c["text"]))
    p.setColor(QPalette.Highlight, QColor(theme.ACCENT))
    p.setColor(QPalette.HighlightedText, QColor(theme.ON_ACCENT))
    p.setColor(QPalette.ToolTipBase, QColor(c["button"]))
    p.setColor(QPalette.ToolTipText, QColor(c["text"]))
    app.setPalette(p)
    app.setStyleSheet(
        f"QLineEdit, QComboBox {{ color: {c['text']}; background: {c['panel']};"
        f" border: 1px solid {c['border']}; border-radius: 5px; padding: 3px 6px; }}")


def _fix_windows_taskbar_icon():
    """Sans ceci, Windows regroupe la fenetre sous l'icone de python.exe/
    pythonw.exe dans la barre des taches (il identifie l'appli par le nom de
    l'executable, pas par setWindowIcon). Lui donner un identifiant propre
    force Windows a utiliser l'icone de la fenetre a la place."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Beheread.MangaReader.1")
    except Exception:
        logging.warning("Echec SetCurrentProcessExplicitAppUserModelID", exc_info=True)


def _initial_file_from_argv(argv) -> str | None:
    """Fichier a ouvrir directement, passe par l'explorateur Windows lors d'un
    double-clic (Beheread declare comme lecteur .cbz par defaut). Renvoie None
    si aucun argument valide : lancement normal sur la bibliotheque."""
    for arg in argv[1:]:
        p = Path(arg)
        if p.is_file():
            # chemin absolu : il peut etre transmis a une instance deja ouverte,
            # dont le dossier courant differe
            return str(p.resolve())
    return None


def main():
    applogging.setup()
    _fix_windows_taskbar_icon()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(appicon.app_icon())   # re-teintee par apply_theme une fois les preferences lues

    initial_file = _initial_file_from_argv(sys.argv)
    # instance unique : si Beheread est deja ouvert, on lui transmet la demande
    # et on s'arrete la, AVANT de charger les donnees (deux processus
    # s'ecraseraient mutuellement progress.json)
    instance = SingleInstance(data_dir() / "instance.lock")
    if not instance.acquire():
        request = {"open": initial_file} if initial_file else {"activate": True}
        if send_to_primary(request, instance.name):
            logging.info("Beheread deja ouvert : demande transmise (%s)", request)
            return
        logging.warning("Instance principale injoignable : lancement autonome")

    try:
        store = Store()
    except DatabaseTooNew:
        logging.exception("Base de donnees trop recente")
        QMessageBox.critical(
            None, APP_NAME,
            "Vos données ont été enregistrées par une version plus récente de Beheread.\n\n"
            "Installez la dernière version de Beheread pour les ouvrir. (Elles n'ont pas "
            "été modifiées.)")
        return
    except Exception:
        # ex. import des anciennes donnees interrompu (il sera retente) ou
        # dossier de donnees inaccessible : message clair plutot qu'un plantage
        logging.exception("Ouverture des donnees impossible")
        QMessageBox.critical(
            None, APP_NAME,
            "Beheread n'a pas pu ouvrir vos données de lecture.\n\n"
            f"Dossier : {data_dir()}\n"
            "Le détail de l'erreur est dans le fichier beheread.log de ce dossier. "
            "Vos données n'ont pas été effacées ; relancez Beheread après avoir "
            "corrigé le problème (espace disque, droits d'accès…).")
        return
    apply_theme(app, store.ui_pref("theme", "dark"), store.ui_pref("accent"))
    window = MainWindow(store)
    instance.messageReceived.connect(window.handle_instance_message)

    if initial_file is not None:
        window.open_file_directly(initial_file)
    else:
        window.showMaximized()
    # filet de securite : ecrit les sauvegardes differees encore en attente,
    # meme si la fenetre est fermee sans passer par closeEvent (ex. quit OS)
    app.aboutToQuit.connect(store.close)
    app.aboutToQuit.connect(instance.release)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
