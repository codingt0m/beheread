"""Textes venus de l'exterieur (ComicInfo.xml, reponses des sources en
ligne, noms de fichiers) : jamais interpretes comme du HTML par Qt, qui y
chargerait par exemple une image distante (voir beheread/ui/safe_text.py)."""

from PySide6.QtGui import QColor, QImage, QPixmap, QTextDocument
from PySide6.QtWidgets import QLabel, QMessageBox

from beheread.ui.library import dialogs
from beheread.ui.library.detail import DetailPanel
from beheread.ui.safe_text import plain

IMAGE_H = 300


def _evil(tmp_path):
    """Texte qui, lu comme du HTML, chargerait une image du disque."""
    img = QImage(400, IMAGE_H, QImage.Format_RGB32)
    img.fill(QColor("red"))
    path = tmp_path / "pixel.png"
    img.save(str(path))
    return f'<img src="{path.as_uri()}">Toriyama'


def test_plain_leaves_ordinary_text_untouched():
    assert plain("Berserk\nTome 3  ·  Miura") == "Berserk\nTome 3  ·  Miura"
    assert plain(None) == ""


def test_plain_text_is_shown_literally_without_loading_anything(qapp, tmp_path):
    evil = _evil(tmp_path)
    # format automatique, comme une infobulle ou une QMessageBox
    assert QLabel(evil).sizeHint().height() >= IMAGE_H   # la menace est reelle
    assert QLabel(plain(evil)).sizeHint().height() < IMAGE_H
    doc = QTextDocument()
    doc.setHtml(plain(f"{evil}\nligne 2"))
    assert doc.toPlainText().replace(" ", "\n") == f"{evil}\nligne 2"


def test_detail_panel_never_renders_metadata_as_html(qtbot, tmp_path):
    evil = _evil(tmp_path)
    panel = DetailPanel()
    qtbot.addWidget(panel)
    panel.show_content(QPixmap(), evil, evil, [("Auteur", evil)], [])
    labels = [w for w in panel.findChildren(QLabel)
              if w.objectName() in ("detailTitle", "detailSub", "detailVal")]
    shown = [w for w in labels if "<img" in w.text()]   # affiche tel quel (titre tronque)
    assert {w.objectName() for w in shown} == {"detailTitle", "detailSub", "detailVal"}
    assert all(w.sizeHint().height() < IMAGE_H for w in shown)


def _login_dialog(qtbot, store, monkeypatch, answer):
    monkeypatch.setattr(dialogs.LocalAuthReceiver, "start", lambda self: None)
    monkeypatch.setattr(dialogs.QDesktopServices, "openUrl", lambda url: True)
    monkeypatch.setattr(dialogs.anilist, "viewer", lambda token: {"id": 7, "name": "intrus"})
    asked, saved = [], []
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda _p, _t, text, *a: asked.append(text) or answer))
    monkeypatch.setattr(store, "set_anilist_login", lambda token, name: saved.append((token, name)))
    dlg = dialogs.AniListLoginDialog(store)
    qtbot.addWidget(dlg)
    dlg._on_token("jeton")
    return asked, saved


def test_anilist_login_is_dropped_unless_the_account_is_confirmed(qtbot, store, monkeypatch):
    """Pendant l'attente, un autre site peut faire parvenir SON jeton a la page
    locale : le compte est montre et doit etre confirme avant d'etre retenu."""
    asked, saved = _login_dialog(qtbot, store, monkeypatch, QMessageBox.No)
    assert "intrus" in asked[0]
    assert saved == []


def test_anilist_login_is_saved_once_confirmed(qtbot, store, monkeypatch):
    _asked, saved = _login_dialog(qtbot, store, monkeypatch, QMessageBox.Yes)
    assert saved == [("jeton", "intrus")]
