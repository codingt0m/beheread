"""Langue de l'interface (beheread/i18n.py) et completude de la traduction
anglaise : chaque texte marque dans le code (tr, trn, N_) doit avoir sa
traduction, avec les memes champs {nom}."""

import ast
import pathlib
import string

import pytest

from beheread import i18n
from beheread.locale import en

ROOT = pathlib.Path(__file__).resolve().parent.parent / "beheread"


def _marked_texts():
    """(fichier, ligne, texte) de chaque texte litteral passe a tr, trn ou N_."""
    found = []
    for path in sorted(ROOT.rglob("*.py")):
        if "perso" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id in ("tr", "N_"):
                args = node.args[:1]
            elif node.func.id == "trn":
                args = node.args[1:3]
            else:
                continue
            for arg in args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append((path.relative_to(ROOT.parent), node.lineno, arg.value))
    return found


def _fields(text):
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name}


@pytest.fixture(autouse=True)
def _french_again():
    yield
    i18n.set_language("fr")


def test_every_marked_text_is_translated_with_the_same_fields():
    missing = [f"{f}:{line}: {text!r}" for f, line, text in _marked_texts()
               if text not in en.CATALOG]
    assert not missing, "Textes sans traduction anglaise :\n" + "\n".join(missing)
    wrong = [f"{text!r} -> {en.CATALOG[text]!r}" for _f, _l, text in _marked_texts()
             if _fields(text) != _fields(en.CATALOG[text])]
    assert not wrong, "Champs differents :\n" + "\n".join(wrong)


def test_language_choice_and_plurals():
    assert i18n.resolve("system", "fr_FR") == "fr" and i18n.resolve("system", "de_DE") == "en"
    assert i18n.resolve("en", "fr_FR") == "en"
    assert i18n.tr("Tome suivant") == "Tome suivant"            # francais : le texte source
    assert i18n.trn(0, "{n} page", "{n} pages") == "0 page"
    i18n.set_language("en")
    assert i18n.tr("Tome suivant") == "Next volume"
    assert i18n.trn(0, "{n} page", "{n} pages") == "0 pages"   # anglais : 0 au pluriel
    assert i18n.tr("Texte inconnu {x}", x=1) == "Texte inconnu 1"   # sans traduction : tel quel
