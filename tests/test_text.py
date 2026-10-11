"""Normalisation de texte partagee (core/text.py)."""

from beheread.core.text import clean_description, genre_fr


def test_online_summary_becomes_plain_text():
    raw = ("Guts, a <i>former</i> mercenary&#039;s tale.<br><br>\n\nHe hunts.<br>"
           "\n(Source: MangaUpdates)")
    assert clean_description(raw) == "Guts, a former mercenary's tale.\n\nHe hunts."
    assert clean_description(None) == ""


def test_genres_are_shown_in_french():
    assert genre_fr("Slice of Life") == "Tranche de vie"
    assert genre_fr("Horror") == "Horreur"
    assert genre_fr("Gourmet") == "Gourmet"   # inconnu : tel quel
