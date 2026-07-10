"""Beheread - lecteur de mangas CBZ / CBR / EPUB pour Windows 10/11
(100% local, hors-ligne).

Lancement :  python main.py
Voir README.md pour l'installation et le support des fichiers CBR.
"""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

import applogging
import theme
from archive_handler import ArchiveError
from hotkey import GlobalHotkey
from library import LibraryWidget
from reader import ReaderWidget
from storage import Store
from version import __version__

APP_NAME = "Beheread"
ICON_PATH = Path(__file__).resolve().parent / "icon.ico"


class ReaderWindow(QMainWindow):
    """Fenetre independante pour le lecteur : s'ouvre par-dessus la
    bibliotheque (masquee pendant ce temps), en fenetre maximisee - pas en
    plein ecran OS tant que l'utilisateur ne le demande pas explicitement."""

    def __init__(self):
        super().__init__()
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
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
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1200, 800)   # taille de repli si l'utilisateur desmaximise

        self.library = LibraryWidget(self.store)
        self.library.mangaActivated.connect(self.open_manga)
        self.library.themeToggleRequested.connect(self.toggle_theme)
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
        self._boss_hotkey = GlobalHotkey(self.toggle_boss)
        app = QApplication.instance()
        app.installNativeEventFilter(self._boss_hotkey)
        app.aboutToQuit.connect(self._boss_hotkey.unregister)

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

        first_open = self.reader_window is None
        if first_open:
            self.reader_window = ReaderWindow()
        win = self.reader_window
        reader.fullscreen_toggled.connect(win.toggle_fullscreen)
        win.setCentralWidget(reader)   # avant showMaximized : la fenetre a deja
        win.setWindowTitle(f"{Path(path).stem}  -  {APP_NAME}")  # son contenu au premier affichage
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
            # dans la meme fenetre, sans repasser par la bibliotheque
            old_reader.archive.close()
            old_reader.deleteLater()

    def _on_open_failed(self):
        """Le fichier passe en ligne de commande n'a pas pu s'ouvrir. En mode
        direct il n'y a pas de bibliotheque de repli : on quitte l'app."""
        if self.direct_mode:
            QApplication.instance().quit()

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

    def toggle_theme(self):
        mode = "light" if self.store.ui_pref("theme", "dark") == "dark" else "dark"
        self.store.set_ui_pref("theme", mode)
        apply_theme(QApplication.instance(), mode)
        self.library.apply_theme()
        if self.reader is not None:
            self.reader.apply_theme()

    def closeEvent(self, event):
        if self.reader is not None:
            self.reader.close_reader()
        self.store.flush()   # garantit l'ecriture des dernieres modifications differees
        super().closeEvent(event)


def apply_theme(app: QApplication, mode: str):
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
    p.setColor(QPalette.HighlightedText, QColor("#f5f0ee"))
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
            return str(p)
    return None


def main():
    applogging.setup()
    _fix_windows_taskbar_icon()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    store = Store()
    apply_theme(app, store.ui_pref("theme", "dark"))
    window = MainWindow(store)

    initial_file = _initial_file_from_argv(sys.argv)
    if initial_file is not None:
        window.open_file_directly(initial_file)
    else:
        window.showMaximized()
    # filet de securite : ecrit les sauvegardes differees encore en attente,
    # meme si la fenetre est fermee sans passer par closeEvent (ex. quit OS)
    app.aboutToQuit.connect(store.flush)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
