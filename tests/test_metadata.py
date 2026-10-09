"""Tests de la cascade de metadonnees (metadata.fetch).

La logique en cinq niveaux (ComicInfo.xml -> Google Books -> AniList ->
MangaDex -> BnF) a une semantique subtile : chaque couche n'est interrogee que si la
precedente n'a rien donne d'exploitable, et un echec reseau ne doit pas etre
mis en cache comme une absence de resultat (network_ok=False). Les clients
reseau sont mockes ; aucun acces reseau reel.
"""

import pytest

from beheread.infra import anilist, bnf, googlebooks, mangadex, metadata


def _no_network(*a, **k):
    raise AssertionError("le reseau ne doit pas etre interroge")


@pytest.fixture(autouse=True)
def _no_bnf(monkeypatch):
    """La BnF, derniere source, n'est jamais interrogee pour de vrai : chaque
    test qui l'atteint la remplace explicitement."""
    monkeypatch.setattr(bnf, "search_series", _no_network)


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
                        lambda name, **k: {"authors": ["Isayama"], "published_year": 2009,
                                      "match_score": 1.0})
    # AniList a repondu -> MangaDex ne doit pas etre interroge
    monkeypatch.setattr(mangadex, "search_series", _no_network)

    data, ok, series = metadata.fetch("x.cbz", "Attack on Titan", 1)
    assert ok is True
    assert data["source"] == "anilist"
    # le dict serie mis en cache porte sa source et la version de la cascade
    assert series == {"authors": ["Isayama"], "published_year": 2009, "match_score": 1.0,
                      "source": "anilist", "cascade_version": metadata.CASCADE_VERSION}


def test_falls_back_to_mangadex(monkeypatch):
    """AniList muet (oeuvre de niche) mais MangaDex la connait : on doit
    recuperer ses metadonnees plutot que de rien renvoyer."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: None)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name, **k: {"authors": ["Toan"], "published_year": 2024,
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

    def al_fail(name, **k):
        raise anilist.AniListError("timeout")
    monkeypatch.setattr(anilist, "search_series", al_fail)

    def md_fail(name, **k):
        raise mangadex.MangaDexError("timeout")
    monkeypatch.setattr(mangadex, "search_series", md_fail)

    def bnf_fail(name):
        raise bnf.BnfError("timeout")
    monkeypatch.setattr(bnf, "search_series", bnf_fail)

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

    cached = {"authors": ["Toriyama"], "published_year": 1984, "source": "anilist",
              "cascade_version": metadata.CASCADE_VERSION}
    data, ok, series = metadata.fetch("x.cbz", "Dragon Ball", 1, cached_series=cached)
    assert ok is True
    assert data["authors"] == ["Toriyama"]
    # la source du cache serie est conservee
    assert data["source"] == "anilist"
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
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: None)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name, **k: {"authors": ["Toan"], "published_year": 2024,
                                      "country": "FR"})

    legacy_cache = {"not_found": True}   # ancien format, sans cascade_version
    data, ok, series = metadata.fetch("x.cbz", "Run to Heaven", 1,
                                      cached_series=legacy_cache)
    assert ok is True
    assert data["authors"] == ["Toan"]
    assert data["source"] == "mangadex"


def test_offline_mode_never_touches_network(monkeypatch):
    """Recherche en ligne non autorisee : aucune API n'est appelee, et
    l'absence de resultat n'est pas presentee comme definitive (ok=False),
    pour etre retentee si l'utilisateur active les metadonnees en ligne."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", _no_network)
    monkeypatch.setattr(anilist, "search_series", _no_network)
    monkeypatch.setattr(mangadex, "search_series", _no_network)
    assert metadata.fetch("x.cbz", "One Piece", 1, None, online=False) == (None, False, None)


def test_offline_mode_still_uses_comicinfo(monkeypatch):
    monkeypatch.setattr(metadata, "_read_comicinfo_meta",
                        lambda path: {"authors": ["Oda"], "published_year": 1997})
    monkeypatch.setattr(googlebooks, "search_volume", _no_network)
    data, ok, _ = metadata.fetch("x.cbz", "One Piece", 1, None, online=False)
    assert ok and data["authors"] == ["Oda"] and data["source"] == "comicinfo"


def test_unrelated_anilist_result_is_ignored(monkeypatch):
    """AniList renvoie toujours « quelque chose » : un titre sans rapport avec
    le nom cherche ne doit pas fournir l'auteur (ni le pays d'origine)."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    monkeypatch.setattr(anilist, "search_series",
                        lambda name, **k: {"authors": ["Hatch"], "published_year": 2014,
                                      "country": "JP", "match_score": 0.2})
    monkeypatch.setattr(mangadex, "search_series", lambda name, **k: None)
    monkeypatch.setattr(bnf, "search_series", lambda name: None)
    data, ok, series = metadata.fetch("x.cbz", "Monster", 6)
    assert data is None and ok is True and series.get("not_found")


def test_falls_back_to_bnf_for_bande_dessinee(monkeypatch):
    """Une BD franco-belge, inconnue des bases manga, est trouvee a la BnF."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: None)
    monkeypatch.setattr(mangadex, "search_series", lambda name, **k: None)
    monkeypatch.setattr(bnf, "search_series",
                        lambda name: {"authors": ["Julien Neel"], "published_year": 2020,
                                      "format": "bd", "title": "Lou ! Sonata"})
    data, ok, series = metadata.fetch("x.cbz", "Lou ! Sonata", 1)
    assert ok is True
    assert data["source"] == "bnf" and data["format"] == "bd"
    assert series["authors"] == ["Julien Neel"]


def test_old_cascade_results_are_stale():
    """Les resultats AniList/MangaDex et les « introuvable » ecrits par une
    cascade plus ancienne sont a retenter ; ComicInfo.xml, Google Books et
    les saisies manuelles ne le sont jamais."""
    current = metadata.CASCADE_VERSION
    assert metadata.is_stale({"not_found": True, "cascade_version": current - 1})
    assert metadata.is_stale({"authors": ["Hatch"], "source": "anilist"})
    assert metadata.is_stale({"authors": ["X"], "source": "series", "cascade_version": 2})
    assert metadata.is_stale({"authors": ["Hatch"], "title": "Otome no Wareme"})   # sans source
    assert not metadata.is_stale({"authors": ["X"], "source": "anilist",
                                  "cascade_version": current})
    assert not metadata.is_stale(metadata.not_found_sentinel())
    for source in ("comicinfo", "googlebooks", "manual"):
        assert not metadata.is_stale({"authors": ["X"], "source": source})


def test_generic_names_are_not_searched(monkeypatch):
    """Un fichier nomme seulement « Volume 1 » n'a pas de nom de serie : rien
    a chercher en ligne (AniList trouverait « Full Volume »)."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", _no_network)
    monkeypatch.setattr(anilist, "search_series", _no_network)
    data, ok, series = metadata.fetch("Volume 1.cbz", "Volume", 1)
    assert data is None and ok is True and series.get("not_found")
    assert metadata.fetch_series("Tome")[0].get("not_found")


def test_exact_bnf_match_beats_approximate_mangadex(monkeypatch):
    """« Walking Dead » : MangaDex ne trouve qu'un titre voisin (« Dead Girl
    Walking »), la BnF le titre exact - c'est lui qui est retenu."""
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: None)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name, **k: {"authors": ["Hino Hideshi"], "country": "JP",
                                      "match_score": 0.83})
    monkeypatch.setattr(bnf, "search_series",
                        lambda name: {"authors": ["Robert Kirkman"], "format": "bd",
                                      "match_score": 1.0})
    series, ok = metadata.fetch_series("Walking Dead")
    assert series["source"] == "bnf" and series["authors"] == ["Robert Kirkman"]


def test_exact_mangadex_match_skips_bnf(monkeypatch):
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: None)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name, **k: {"authors": ["Toan"], "country": "FR", "match_score": 1.0})
    series, ok = metadata.fetch_series("Run to Heaven")   # BnF non interrogee (_no_bnf)
    assert series["source"] == "mangadex"


def test_fallback_without_anilist_is_provisional(monkeypatch):
    """AniList injoignable (limite de requetes) : MangaDex peut trouver un
    homonyme (« Vagabond » colorise a Hong Kong). Son resultat est affiche
    mais provisoire, et reverifie plus tard."""
    def al_fail(name, **k):
        raise anilist.AniListError("429")
    monkeypatch.setattr(anilist, "search_series", al_fail)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name, **k: {"authors": ["Inoue"], "country": "CN", "match_score": 1.0})
    series, ok = metadata.fetch_series("Vagabond")
    assert series["source"] == "mangadex" and series["partial"] is True
    assert metadata.is_stale(series)


def test_fallback_after_anilist_answered_is_final(monkeypatch):
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: None)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name, **k: {"authors": ["Toan"], "country": "FR", "match_score": 1.0})
    series, ok = metadata.fetch_series("Run to Heaven")
    assert "partial" not in series and not metadata.is_stale(series)
