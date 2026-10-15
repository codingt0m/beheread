"""Langue de l'interface : choix dans les preferences, application au
lancement et fenetres construites en anglais."""

import datetime as dt

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton

from beheread import i18n
from beheread.app import apply_language
from beheread.ui import theme
from beheread.ui.library.dialogs import PreferencesDialog, explain_archive_error


@pytest.fixture(autouse=True)
def _french_again():
    yield
    i18n.set_language("fr")


def test_language_is_chosen_in_the_preferences(qtbot, store):
    dlg = PreferencesDialog(store, theme.colors("dark"), {})
    qtbot.addWidget(dlg)
    assert dlg.language.currentData() == "system"
    assert [dlg.language.itemData(i) for i in range(dlg.language.count())] == ["system", "fr", "en"]
    dlg.language.setCurrentIndex(dlg.language.findData("en"))
    dlg.save()
    assert store.ui_pref("language") == "en"


def test_apply_language_follows_the_preference(qapp):
    apply_language(QApplication.instance(), "en")
    assert i18n.language() == "en"
    apply_language(QApplication.instance(), "fr")
    assert i18n.language() == "fr"


def test_library_and_preferences_are_built_in_english(qtbot, store):
    from beheread.app import MainWindow
    i18n.set_language("en")
    win = MainWindow(store)
    qtbot.addWidget(win)
    names = {b.accessibleName() for b in win.library.header.findChildren(QToolButton, "headerBtn")}
    assert names == {"Manage source folders", "Refresh", "Reading statistics", "Preferences"}
    assert win.library.search_edit.placeholderText().startswith("Search for")

    dlg = PreferencesDialog(store, theme.colors("dark"), {})
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "Preferences"
    assert "Save" in {b.text() for b in dlg.findChildren(QPushButton)}


def test_statistics_are_built_in_english(qtbot, store):
    from beheread.ui.stats_view import StatsDialog
    i18n.set_language("en")
    library = {"unread": 1, "reading": 0, "finished": 1, "remaining_pages": 0, "unknown_pages": 0}
    dlg = StatsDialog(store, library, "dark", today=dt.date(2026, 10, 11))
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "Reading statistics"
    assert dlg.tiles[0].label == "Reading time"
    assert dlg.close_button.text() == "Close"


def test_archive_errors_are_explained_in_both_languages():
    french = "Aucune image trouvée dans l'archive :\nx.cbz"
    assert explain_archive_error(french) == "Ce fichier ne contient aucune page à afficher."
    i18n.set_language("en")
    assert explain_archive_error(french) == "This file has no page to show."
    assert explain_archive_error("No image found in the archive:\nx.cbz") == \
        "This file has no page to show."
    assert explain_archive_error("Password-protected PDF:\nx.pdf").startswith("This PDF")


def test_numbers_and_plurals_follow_the_language():
    assert i18n.fmt_int(12345) == "12 345" and i18n.fmt_decimal(2.5) == "2,5"
    assert i18n.trn(1500, "{n} page", "{n} pages") == "1 500 pages"
    i18n.set_language("en")
    assert i18n.fmt_int(12345) == "12,345" and i18n.fmt_decimal(2.5) == "2.5"


def _accept_with_language(monkeypatch, code):
    """Le dialogue des preferences est valide avec cette langue choisie."""
    from PySide6.QtWidgets import QDialog

    from beheread.ui.library import services

    def exec_(dlg):
        dlg.language.setCurrentIndex(dlg.language.findData(code))
        return QDialog.Accepted
    monkeypatch.setattr(services.PreferencesDialog, "exec", exec_)


def test_changing_the_language_restarts_beheread(qtbot, window, monkeypatch):
    lib = window.library
    window.store.set_ui_pref("language", "fr")   # independant de la langue du systeme
    _accept_with_language(monkeypatch, "en")
    with qtbot.waitSignal(lib.restartRequested, timeout=1000):
        lib.open_preferences()
    assert window.store.ui_pref("language") == "en"


def test_keeping_the_language_does_not_restart(qtbot, window, monkeypatch):
    lib = window.library
    window.store.set_ui_pref("language", "fr")   # independant de la langue du systeme
    _accept_with_language(monkeypatch, "fr")
    with qtbot.assertNotEmitted(lib.restartRequested):
        lib.open_preferences()


def test_restart_command_relaunches_the_same_way(monkeypatch, tmp_path):
    import sys

    from beheread import app, platforms
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "beheread" / "__main__.py")])
    assert app.restart_command() == (sys.executable, ["-m", "beheread"])
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "main.py")])
    assert app.restart_command() == (sys.executable, [str((tmp_path / "main.py").resolve())])

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Beheread.exe"))
    monkeypatch.setattr(platforms, "IS_MACOS", False)
    assert app.restart_command() == (str(tmp_path / "Beheread.exe"), [])
    bundle = tmp_path / "Beheread.app"
    monkeypatch.setattr(sys, "executable", str(bundle / "Contents" / "MacOS" / "Beheread"))
    monkeypatch.setattr(platforms, "IS_MACOS", True)
    assert app.restart_command() == ("open", ["-n", str(bundle)])
