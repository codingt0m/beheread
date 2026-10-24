"""Saisies aux couleurs de l'application (remplacent QInputDialog) : la
validation s'affiche sous le champ et bloque le bouton principal."""

from beheread.ui import theme
from beheread.ui.library.prompt import PromptDialog
from tests.ui.conftest import make_cbz, scanned


def _dialog(qtbot, **kwargs):
    dlg = PromptDialog("Titre", "Nom :", theme.colors("dark"), **kwargs)
    qtbot.addWidget(dlg)
    return dlg


def test_invalid_input_is_explained_under_the_field_and_blocks_ok(qtbot):
    dlg = _dialog(qtbot, text="abc", validate=lambda t: "Trop court" if len(t) < 3 else "")
    assert dlg.ok.isEnabled() and dlg.error.isHidden()
    dlg.field.setText("ab")
    assert not dlg.ok.isEnabled() and not dlg.error.isHidden()
    assert dlg.error.text() == "Trop court"
    dlg.field.setText("abc")
    assert dlg.ok.isEnabled() and dlg.error.isHidden()
    assert dlg.value() == "abc"


def test_choice_can_be_picked_or_typed(qtbot):
    dlg = _dialog(qtbot, choices=["Alpha", "Beta"], editable=True)
    assert dlg.value() == "Alpha"
    dlg.field.setCurrentText("Gamma")
    assert dlg.value() == "Gamma"
    fixed = _dialog(qtbot, choices=["Alpha", "Beta"], editable=False)
    fixed.field.setCurrentIndex(1)
    assert fixed.value() == "Beta"


def test_rename_file_checks_the_name_before_validating(window, qtbot, store, mangas):
    first = make_cbz(mangas, "Alpha - Tome 1", seed=1)
    make_cbz(mangas, "Alpha - Tome 2", seed=2)
    store.add_folder(str(mangas))
    lib = window.library
    lib.refresh()
    scanned(qtbot, lib, 2)
    from pathlib import Path
    p = Path(first)
    assert lib._stem_error(p, "Alpha - Tome 1") == ""          # inchange : rien a dire
    assert "caractères" in lib._stem_error(p, "a:b")
    assert "réservé" in lib._stem_error(p, "CON")
    assert "existe déjà" in lib._stem_error(p, "Alpha - Tome 2")
    assert lib._stem_error(p, "Alpha - Tome 3") == ""
