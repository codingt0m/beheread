"""Tests de la cascade de metadonnees (metadata.fetch).

La logique en quatre niveaux (ComicInfo.xml -> Google Books -> AniList ->
MangaDex) a une semantique subtile : chaque couche n'est interrogee que si la
precedente n'a rien donne d'exploitable, et un echec reseau ne doit pas etre
mis en cache comme une absence de resultat (network_ok=False). Les clients
reseau sont mockes ; aucun acces reseau reel.
"""

import anilist
import googlebooks
import mangadex
import metadata


def _no_network(*a, **k):
    raise AssertionError("le reseau ne doit pas etre interroge")


def test_comicinfo_wins_without_network(monkeypatch):
    monkeypatch.setattr(metadata, "_read_comicinfo_meta",
                        lambda path: {"authors": ["Kentaro Miura"], "published_year": 1990})
    # si le reseau etait touche, ce serait un bug -> on le fait exploser
    monkeypatch.setattr(googlebooks, "search_volume", _no_network)
    monkeypatch.setattr(anilist, "search_series", _no_network)
    monkeypatch.setattr(mangadex, "search_series", _no_network)

    data, ok, series = metadata.fetch("x.cbz", "Berserk", 3)
    assert ok is True
    assert data["source"] == "comicinfo"
    assert data["authors"] == ["Kentaro Miura"]
    assert series is None


def test_falls_back_to_googlebooks(monkeypatch):
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume",
                        lambda name, vol, **k: {"authors": ["Oda"], "published_year": 1997})
    monkeypatch.setattr(anilist, "search_series", _no_network)
    monkeypatch.setattr(mangadex, "search_series", _no_network)

    data, ok, series = metadata.fetch("x.cbz", "One Piece", 1)
    assert ok is True
    assert data["source"] == "googlebooks"


def test_falls_back_to_anilist(monkeypatch):
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    monkeypatch.setattr(anilist, "search_series",
                        lambda name: {"authors": ["Isayama"], "published_year": 2009})
    # AniList a repondu -> MangaDex ne doit pas etre interroge
    monkeypatch.setattr(mangadex, "search_series", _no_network)

    data, ok, series = metadata.fetch("x.cbz", "Attack on Titan", 1)
    assert ok is True
    assert data["source"] == "anilist"
    # le dict serie mis en cache porte desormais sa source
    assert series == {"authors": ["Isayama"], "published_year": 2009,
                      "source": "anilist"}


def test_falls_back_to_mangadex(monkeypatch):
    """AniList muet (oeuvre de niche) mais MangaDex la connait : on doit
    recuperer ses metadonnees plutot que de rien renvoyer."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    monkeypatch.setattr(anilist, "search_series", lambda name: None)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name: {"authors": ["Toan"], "published_year": 2024,
                                      "country": "FR", "title": "Run to Heaven"})

    data, ok, series = metadata.fetch("x.cbz", "Run to Heaven", 1)
    assert ok is True
    assert data["source"] == "mangadex"
    assert data["authors"] == ["Toan"]
    assert data["country"] == "FR"
    # le resultat MangaDex est aussi renvoye comme donnees serie a cacher
    assert series["authors"] == ["Toan"]


def test_network_failure_not_cached(monkeypatch):
    """Un echec reseau doit remonter network_ok=False pour que l'appelant ne
    mette PAS en cache une absence de resultat (a retenter plus tard)."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)

    def gb_fail(name, vol, **k):
        raise googlebooks.GoogleBooksError("429 too many requests")
    monkeypatch.setattr(googlebooks, "search_volume", gb_fail)

    def al_fail(name):
        raise anilist.AniListError("timeout")
    monkeypatch.setattr(anilist, "search_series", al_fail)

    def md_fail(name):
        raise mangadex.MangaDexError("timeout")
    monkeypatch.setattr(mangadex, "search_series", md_fail)

    data, ok, series = metadata.fetch("x.cbz", "Obscure Title", 1)
    assert data is None
    assert ok is False
    assert series is None


def test_googlebooks_title_matching():
    """Le resultat Google Books n'est retenu que si son titre correspond
    vraiment a la serie demandee (sinon on risque un auteur/date faux)."""
    assert googlebooks._title_matches("One Piece", "One Piece, Vol. 12")
    assert googlebooks._title_matches("Gloutons et Dragons", "Gloutons & Dragons Tome 3")
    assert googlebooks._title_matches("Berserk", "Berserk Deluxe Edition Volume 1")
    # titres sans rapport : rejetes -> repli sur AniList
    assert not googlebooks._title_matches("Gloutons et Dragons", "Dungeon Meshi")
    assert not googlebooks._title_matches("Parasite", "The Selfish Gene")
    assert not googlebooks._title_matches("One Piece", "")


def test_cached_series_skips_network(monkeypatch):
    """Si le repli serie est deja en cache, on ne re-interroge aucune source."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    monkeypatch.setattr(anilist, "search_series", _no_network)
    monkeypatch.setattr(mangadex, "search_series", _no_network)

    cached = {"authors": ["Toriyama"], "published_year": 1984}
    data, ok, series = metadata.fetch("x.cbz", "Dragon Ball", 1, cached_series=cached)
    assert ok is True
    assert data["authors"] == ["Toriyama"]
    # source generique : l'origine exacte (anilist/mangadex) n'est pas reconstituee
    assert data["source"] == "series"
    # deja fourni via cache : rien de neuf a re-sauvegarder
    assert series is None


def test_cached_series_not_found_skips_network(monkeypatch):
    """Un cache serie "not_found" A JOUR (meme cascade_version) doit
    court-circuiter tout le reseau serie."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    monkeypatch.setattr(anilist, "search_series", _no_network)
    monkeypatch.setattr(mangadex, "search_series", _no_network)

    data, ok, series = metadata.fetch("x.cbz", "Dragon Ball", 1,
                                      cached_series=metadata.not_found_sentinel())
    assert data is None
    assert ok is True
    assert series is None


def test_stale_not_found_cache_is_retried(monkeypatch):
    """Un cache serie "not_found" ECRIT PAR UNE CASCADE PLUS ANCIENNE (sans
    cascade_version, ou une version inferieure - ex. avant l'ajout de
    MangaDex) ne doit PAS bloquer une nouvelle recherche : une source ajoutee
    depuis peut desormais trouver la serie."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    monkeypatch.setattr(anilist, "search_series", lambda name: None)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name: {"authors": ["Toan"], "published_year": 2024,
                                      "country": "FR"})

    legacy_cache = {"not_found": True}   # ancien format, sans cascade_version
    data, ok, series = metadata.fetch("x.cbz", "Run to Heaven", 1,
                                      cached_series=legacy_cache)
    assert ok is True
    assert data["authors"] == ["Toan"]
    assert data["source"] == "mangadex"
