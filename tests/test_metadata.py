"""Tests de la cascade de metadonnees (metadata.fetch, metadata.fetch_series).

La logique a une semantique subtile : chaque couche n'est interrogee que si
la precedente n'a rien donne d'exploitable, la BnF decide de la nature de
l'oeuvre (une BD ou un comics n'est jamais confie aux bases manga), et un
echec reseau ne doit pas etre mis en cache comme une absence de resultat
(network_ok=False). Les clients reseau sont mockes ; aucun acces reseau reel.
"""

import json

import pytest

from beheread.infra import anilist, bnf, googlebooks, mangadex, metadata, wikidata


def _no_network(*a, **k):
    raise AssertionError("le reseau ne doit pas etre interroge")


@pytest.fixture(autouse=True)
def _quiet_sources(monkeypatch):
    """Par defaut, la BnF et Wikidata ne connaissent rien, aucun code-barres
    n'est lu, et la memoire de session est vide : chaque test configure les
    sources qu'il atteint."""
    monkeypatch.setattr(bnf, "search_series", lambda name, **k: None)
    monkeypatch.setattr(bnf, "search_isbn", _no_network)
    monkeypatch.setattr(wikidata, "search_series", lambda name, **k: None)
    monkeypatch.setattr(metadata, "_scan_isbn", lambda path: None)
    metadata.clear_series_memo()
    yield
    metadata.clear_series_memo()


def _offline_series(monkeypatch):
    for module in (anilist, mangadex, bnf, wikidata):
        monkeypatch.setattr(module, "search_series", _no_network)


def test_comicinfo_wins_without_network(monkeypatch):
    monkeypatch.setattr(metadata, "_read_comicinfo_meta",
                        lambda path: {"authors": ["Kentaro Miura"], "published_year": 1990})
    monkeypatch.setattr(googlebooks, "search_volume", _no_network)
    _offline_series(monkeypatch)
    data, ok, series = metadata.fetch("x.cbz", "Berserk", 3)
    assert ok is True
    assert data["source"] == "comicinfo"
    assert data["authors"] == ["Kentaro Miura"]
    assert series is None


def test_local_metadata_reads_comicinfo_extras_and_series_json(tmp_path, monkeypatch):
    """Comme Komga : nombre de tomes, genres et resume de ComicInfo.xml,
    completes par le series.json de Mylar du dossier."""
    (tmp_path / "series.json").write_text(json.dumps({"metadata": {
        "name": "Saga", "year": 2012, "publisher": "Image", "total_issues": 66,
        "description_text": "Alana et Marko..."}}), encoding="utf-8")

    class _Archive:
        def __init__(self, path):
            pass

        def read_comicinfo(self):
            return {"authors": ["Brian K. Vaughan"], "year": 2013, "count": 12,
                    "genres": ["Science-fiction"], "summary": None, "gtin": "9782365772501",
                    "embedded": "comicinfo"}

        def close(self):
            pass
    monkeypatch.setattr(metadata, "Archive", _Archive)
    local = metadata._read_comicinfo_meta(str(tmp_path / "Saga 01.cbz"))
    assert local["volumes"] == 12 and local["genres"] == ["Science-fiction"]
    assert local["description"] == "Alana et Marko..."   # du series.json
    assert local["isbn"] == "9782365772501" and local["embedded"] == "comicinfo"
    data, ok, _ = metadata.fetch(str(tmp_path / "Saga 01.cbz"), "Saga", 1, online=False)
    assert data["source"] == "comicinfo" and data["volumes"] == 12


def test_series_json_alone_gives_the_series_start(tmp_path, monkeypatch):
    (tmp_path / "series.json").write_text(json.dumps({"metadata": {"year": 2012}}),
                                          encoding="utf-8")
    monkeypatch.setattr(metadata, "Archive", lambda path: (_ for _ in ()).throw(OSError()))
    local = metadata._read_comicinfo_meta(str(tmp_path / "Saga 01.cbz"))
    assert local["published_year"] == 2012 and local["embedded"] == "seriesjson"


def test_isbn_identifies_the_volume(monkeypatch):
    """Code-barres lu sur la quatrieme de couverture : la notice BnF de ce
    tome precis, sans recherche de serie."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(metadata, "_scan_isbn", lambda path: "9782505063520")
    monkeypatch.setattr(bnf, "search_isbn", lambda isbn: {
        "title": "Celui qui part", "series": "Les vieux fourneaux", "number": 3,
        "authors": ["Wilfrid Lupano"], "published_year": 2015, "format": "bd",
        "origin": "fre", "isbn": isbn})
    _offline_series(monkeypatch)
    monkeypatch.setattr(googlebooks, "search_volume", _no_network)
    data, ok, series = metadata.fetch("x.cbz", "Les Vieux Fourneaux", 3)
    assert data["source"] == "isbn" and data["published_year"] == 2015
    assert data["title"] == "Les vieux fourneaux"
    assert data["titles"] == ["Les vieux fourneaux", "Celui qui part"]
    assert ok and series is None


def test_isbn_of_another_book_is_ignored(monkeypatch):
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(metadata, "_scan_isbn", lambda path: "9782505063520")
    monkeypatch.setattr(bnf, "search_isbn", lambda isbn: {
        "title": "Tintin au Tibet", "series": "Les aventures de Tintin", "number": 20,
        "authors": ["Hergé"], "published_year": 1960})
    monkeypatch.setattr(bnf, "search_series", lambda name, **k: {
        "authors": ["Wilfrid Lupano"], "published_year": 2014, "origin": "fre", "format": "bd",
        "match_score": 1.0})
    monkeypatch.setattr(anilist, "search_series", _no_network)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    data, ok, series = metadata.fetch("x.cbz", "Les Vieux Fourneaux", 3)
    assert data["source"] == "bnf" and data["authors"] == ["Wilfrid Lupano"]


def test_volume_date_comes_from_the_series_before_google_books(monkeypatch):
    """La BnF date chaque tome : Google Books (quota tres bas) n'est pas
    interroge."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(bnf, "search_series", lambda name, **k: {
        "authors": ["Jean Van Hamme"], "published_year": 1980, "origin": "fre", "format": "bd",
        "volume_years": {"1": 1980, "2": 1981}, "volumes": 2, "match_score": 1.0})
    monkeypatch.setattr(googlebooks, "search_volume", _no_network)
    data, ok, series = metadata.fetch("x.cbz", "Thorgal", 2)
    assert data["source"] == "bnf" and data["published_year"] == 1981
    assert "volume_years" not in data and series["volume_years"]["2"] == 1981


def test_falls_back_to_googlebooks_for_the_volume_date(monkeypatch):
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(anilist, "search_series",
                        lambda name, **k: {"authors": ["Oda"], "published_year": 1997,
                                           "match_score": 1.0})
    monkeypatch.setattr(googlebooks, "search_volume",
                        lambda name, vol, **k: {"authors": ["Oda"], "published_year": 2001,
                                                "publisher": None})
    data, ok, series = metadata.fetch("x.cbz", "One Piece", 12)
    assert ok is True
    assert data["source"] == "googlebooks" and data["published_year"] == 2001
    assert "publisher" not in data                 # valeurs vides retirees
    assert series["source"] == "anilist"           # serie fraiche a mettre en cache


def test_falls_back_to_anilist(monkeypatch):
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    calls = []

    def al(name, **k):
        calls.append(k)
        return {"authors": ["Isayama"], "published_year": 2009, "match_score": 1.0}
    monkeypatch.setattr(anilist, "search_series", al)
    # AniList a repondu -> MangaDex ne doit pas etre interroge
    monkeypatch.setattr(mangadex, "search_series", _no_network)

    data, ok, series = metadata.fetch("x.cbz", "Attack on Titan", 1)
    assert ok is True
    assert data["source"] == "anilist"
    assert calls[0]["adult"] is False   # oeuvres pour adultes ecartees
    # le dict serie mis en cache porte sa source et la version de la cascade
    assert series == {"authors": ["Isayama"], "published_year": 2009, "match_score": 1.0,
                      "source": "anilist", "cascade_version": metadata.CASCADE_VERSION}


def test_falls_back_to_mangadex(monkeypatch):
    """AniList muet (oeuvre de niche) mais MangaDex la connait."""
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
    assert series["authors"] == ["Toan"]


def test_network_failure_not_cached(monkeypatch):
    """Un echec reseau doit remonter network_ok=False pour que l'appelant ne
    mette PAS en cache une absence de resultat (a retenter plus tard)."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)

    def fail(error):
        def raiser(*a, **k):
            raise error("timeout")
        return raiser
    monkeypatch.setattr(googlebooks, "search_volume", fail(googlebooks.GoogleBooksError))
    monkeypatch.setattr(anilist, "search_series", fail(anilist.AniListError))
    monkeypatch.setattr(mangadex, "search_series", fail(mangadex.MangaDexError))
    monkeypatch.setattr(bnf, "search_series", fail(bnf.BnfError))
    monkeypatch.setattr(wikidata, "search_series", fail(wikidata.WikidataError))

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
    assert not googlebooks._title_matches("Gloutons et Dragons", "Dungeon Meshi")
    assert not googlebooks._title_matches("Parasite", "The Selfish Gene")
    assert not googlebooks._title_matches("One Piece", "")


def test_googlebooks_manga_category(monkeypatch):
    info = {"title": "One Piece", "authors": ["Eiichirō Oda"], "publishedDate": "2001-05",
            "categories": ["Comics & Graphic Novels / Manga / Action & Adventure"],
            "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9782723434621"}]}
    monkeypatch.setattr(googlebooks, "_get", lambda params: {"items": [{"volumeInfo": info}]})
    r = googlebooks.search_volume("One Piece", 12)
    assert r["format"] == "manga" and r["isbn"] == "9782723434621" and r["published_year"] == 2001
    info["categories"] = ["Comics & Graphic Novels / Superheroes"]
    assert "format" not in googlebooks.search_volume("One Piece", 12)   # aucun indice de sens


def test_cached_series_skips_network(monkeypatch):
    """Si le repli serie est deja en cache, on ne re-interroge aucune source."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    _offline_series(monkeypatch)
    cached = {"authors": ["Toriyama"], "published_year": 1984, "source": "anilist",
              "cascade_version": metadata.CASCADE_VERSION}
    data, ok, series = metadata.fetch("x.cbz", "Dragon Ball", 1, cached_series=cached)
    assert ok is True
    assert data["authors"] == ["Toriyama"]
    assert data["source"] == "anilist"
    assert series is None


def test_cached_series_not_found_skips_network(monkeypatch):
    """Un cache serie "not_found" A JOUR doit court-circuiter tout le reseau
    serie."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    _offline_series(monkeypatch)
    data, ok, series = metadata.fetch("x.cbz", "Dragon Ball", 1,
                                      cached_series=metadata.not_found_sentinel())
    assert data is None
    assert ok is True
    assert series is None


def test_stale_not_found_cache_is_retried(monkeypatch):
    """Un cache serie "not_found" ecrit par une cascade plus ancienne ne doit
    PAS bloquer une nouvelle recherche : une source ajoutee depuis peut
    desormais trouver la serie."""
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", lambda name, vol, **k: None)
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: None)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name, **k: {"authors": ["Toan"], "published_year": 2024,
                                           "country": "FR"})
    data, ok, series = metadata.fetch("x.cbz", "Run to Heaven", 1,
                                      cached_series={"not_found": True})
    assert ok is True
    assert data["authors"] == ["Toan"]
    assert data["source"] == "mangadex"


def test_offline_mode_never_touches_network(monkeypatch):
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", _no_network)
    monkeypatch.setattr(metadata, "_scan_isbn", _no_network)
    _offline_series(monkeypatch)
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
                        lambda name, **k: {"authors": ["Halumoto"], "published_year": 2012,
                                           "country": "JP", "match_score": 0.61})
    monkeypatch.setattr(mangadex, "search_series", lambda name, **k: None)
    data, ok, series = metadata.fetch("x.cbz", "Sandman", 6)
    assert data is None and ok is True and series.get("not_found")


def test_translated_comics_never_reach_the_manga_sources(monkeypatch):
    """« Saga » : la BnF dit que l'oeuvre est traduite de l'anglais - AniList
    (qui trouverait un hentai homonyme) n'est pas interroge."""
    monkeypatch.setattr(bnf, "search_series", lambda name, **k: {
        "authors": ["Brian K Vaughan"], "published_year": 2013, "origin": "eng", "format": "bd",
        "volumes": 12, "match_score": 1.0})
    monkeypatch.setattr(anilist, "search_series", _no_network)
    monkeypatch.setattr(mangadex, "search_series", _no_network)
    series, ok = metadata.fetch_series("Saga")
    assert series["source"] == "bnf" and series["volumes"] == 12 and ok


def test_translated_manga_uses_the_manga_sources(monkeypatch):
    monkeypatch.setattr(bnf, "search_series", lambda name, **k: {
        "authors": ["Naoki Urasawa"], "creators": ["Naoki Urasawa"], "published_year": 2001,
        "origin": "jpn", "format": "manga", "match_score": 1.0})
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: {
        "authors": ["Naoki Urasawa"], "published_year": 1994, "country": "JP",
        "genres": ["Drame"], "match_score": 1.0})
    series, ok = metadata.fetch_series("Monster")
    assert series["source"] == "anilist" and series["genres"] == ["Drame"]


def test_adult_works_need_authors_confirmed_by_bnf(monkeypatch):
    calls = []

    def al(name, **k):
        calls.append(k["adult"])
        return {"authors": ["Shuuzou Oshimi"], "country": "JP", "match_score": 1.0}
    monkeypatch.setattr(anilist, "search_series", al)
    metadata.fetch_series("Welcome Back Alice")
    metadata.clear_series_memo()
    monkeypatch.setattr(bnf, "search_series", lambda name, **k: {
        "authors": ["Shūzō Oshimi"], "creators": ["Shūzō Oshimi"], "origin": "jpn",
        "format": "manga", "published_year": 2021, "match_score": 1.0})
    series, _ok = metadata.fetch_series("Welcome Back Alice")
    assert calls == [False, True] and series["source"] == "anilist"


def test_manga_homonym_with_other_authors_is_rejected(monkeypatch):
    """La BnF connait le « Monster » d'Urasawa ; AniList et MangaDex
    proposent un « MONSTER » coreen : la notice BnF est gardee."""
    monkeypatch.setattr(bnf, "search_series", lambda name, **k: {
        "authors": ["Naoki Urasawa"], "creators": ["Naoki Urasawa"], "published_year": 2001,
        "origin": "jpn", "format": "manga", "match_score": 1.0})
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: {
        "authors": ["Kim Hyun"], "country": "KR", "match_score": 1.0})
    monkeypatch.setattr(mangadex, "search_series", lambda name, **k: {
        "authors": ["Kim Hyun"], "country": "KR", "match_score": 1.0})
    series, ok = metadata.fetch_series("Monster")
    assert series["source"] == "bnf" and series["authors"] == ["Naoki Urasawa"]


def test_french_work_needs_an_exact_manga_match(monkeypatch):
    """Manga francais (Radiant) : la base manga est retenue pour un titre
    exact du meme auteur ; une BD jeunesse inconnue des bases manga
    (Mortelle Adèle) reste une BD, lue de gauche a droite."""
    radiant = {"authors": ["Tony Valente"], "creators": ["Tony Valente"],
               "published_year": 2013, "origin": "fre", "format": None, "match_score": 1.0}
    monkeypatch.setattr(bnf, "search_series", lambda name, **k: radiant)
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: {
        "authors": ["Niiro Ikuhana"], "country": "JP", "match_score": 1.0})
    monkeypatch.setattr(mangadex, "search_series", lambda name, **k: {
        "authors": ["Tony Valente"], "country": "FR", "match_score": 1.0})
    series, _ok = metadata.fetch_series("Radiant")
    assert series["source"] == "mangadex" and series["country"] == "FR"

    metadata.clear_series_memo()
    monkeypatch.setattr(bnf, "search_series", lambda name, **k: dict(
        radiant, authors=["Mr Tan"], creators=["Mr Tan"]))
    monkeypatch.setattr(mangadex, "search_series", lambda name, **k: {
        "authors": ["Toan"], "country": "FR", "match_score": 0.8})
    series, _ok = metadata.fetch_series("Mortelle Adele")
    assert series["source"] == "bnf" and series["format"] == "bd"


def test_wikidata_vetoes_a_manga_homonym_of_a_comics(monkeypatch):
    """La BnF ne connait pas la serie ; AniList trouve un manga « Invincible »,
    Wikidata ne connait sous ce nom qu'un comics americain : c'est lui."""
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: {
        "authors": ["Takeshi Seshimo"], "country": "JP", "match_score": 1.0})
    monkeypatch.setattr(wikidata, "search_series", lambda name, **k: {
        "authors": ["Robert Kirkman"], "published_year": 2003, "country": "US", "format": "bd",
        "kind": "comics", "kinds": ["comics"], "match_score": 1.0})
    series, ok = metadata.fetch_series("Invincible")
    assert series["source"] == "wikidata" and series["format"] == "bd"


def test_wikidata_does_not_veto_when_a_manga_also_exists(monkeypatch):
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: {
        "authors": ["Takeshi Seshimo"], "country": "JP", "match_score": 1.0})
    monkeypatch.setattr(wikidata, "search_series", lambda name, **k: {
        "authors": ["Robert Kirkman"], "kind": "comics", "kinds": ["comics", "manga"],
        "match_score": 1.0})
    series, ok = metadata.fetch_series("Invincible")
    assert series["source"] == "anilist"


def test_wikidata_is_the_last_resort(monkeypatch):
    """« Lastman » : ni la BnF (sous ce titre) ni les bases manga."""
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: None)
    monkeypatch.setattr(mangadex, "search_series", lambda name, **k: None)
    monkeypatch.setattr(wikidata, "search_series", lambda name, **k: {
        "authors": ["Bastien Vivès"], "published_year": 2013, "country": "FR", "format": "bd",
        "kind": "comics", "kinds": ["comics"], "match_score": 1.0})
    series, ok = metadata.fetch_series("Lastman")
    assert series["source"] == "wikidata" and series["authors"] == ["Bastien Vivès"]


def test_old_cascade_results_are_stale():
    """Les resultats en ligne au niveau serie et les « introuvable » ecrits
    par une cascade plus ancienne sont a retenter ; les metadonnees locales,
    Google Books, l'ISBN et les saisies manuelles ne le sont jamais."""
    current = metadata.CASCADE_VERSION
    assert metadata.is_stale({"not_found": True, "cascade_version": current - 1})
    assert metadata.is_stale({"authors": ["Hatch"], "source": "anilist"})
    assert metadata.is_stale({"authors": ["X"], "source": "bnf", "cascade_version": current - 1})
    assert metadata.is_stale({"authors": ["X"], "source": "series", "cascade_version": 2})
    assert metadata.is_stale({"authors": ["Hatch"], "title": "Otome no Wareme"})   # sans source
    assert not metadata.is_stale({"authors": ["X"], "source": "anilist",
                                  "cascade_version": current})
    assert not metadata.is_stale(metadata.not_found_sentinel())
    for source in ("comicinfo", "epub", "seriesjson", "googlebooks", "manual", "isbn"):
        assert not metadata.is_stale({"authors": ["X"], "source": source})


def test_generic_names_are_not_searched(monkeypatch):
    monkeypatch.setattr(metadata, "_read_comicinfo_meta", lambda path: None)
    monkeypatch.setattr(googlebooks, "search_volume", _no_network)
    _offline_series(monkeypatch)
    data, ok, series = metadata.fetch("Volume 1.cbz", "Volume", 1)
    assert data is None and ok is True and series.get("not_found")
    assert metadata.fetch_series("Tome")[0].get("not_found")


def test_exact_bnf_match_beats_approximate_mangadex(monkeypatch):
    """Nature indecise a la BnF : MangaDex ne trouve qu'un titre voisin
    (« Dead Girl Walking »), la BnF le titre exact - c'est lui qui est retenu."""
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: None)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name, **k: {"authors": ["Hino Hideshi"], "country": "JP",
                                           "match_score": 0.83})
    monkeypatch.setattr(bnf, "search_series",
                        lambda name, **k: {"authors": ["Robert Kirkman"], "format": None,
                                           "origin": None, "match_score": 1.0})
    series, ok = metadata.fetch_series("Walking Dead")
    assert series["source"] == "bnf" and series["authors"] == ["Robert Kirkman"]


def test_exact_mangadex_match_skips_wikidata_when_bnf_knows(monkeypatch):
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: None)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name, **k: {"authors": ["Toan"], "country": "FR", "match_score": 1.0})
    monkeypatch.setattr(bnf, "search_series", lambda name, **k: {
        "authors": ["Toan"], "origin": "jpn", "format": "manga", "match_score": 1.0})
    monkeypatch.setattr(wikidata, "search_series", _no_network)
    series, ok = metadata.fetch_series("Run to Heaven")
    assert series["source"] == "mangadex"


def test_fallback_without_anilist_is_provisional(monkeypatch):
    """AniList injoignable (limite de requetes) : MangaDex peut trouver un
    homonyme. Son resultat est affiche mais provisoire, et reverifie plus tard."""
    def al_fail(name, **k):
        raise anilist.AniListError("429")
    monkeypatch.setattr(anilist, "search_series", al_fail)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name, **k: {"authors": ["Inoue"], "country": "CN", "match_score": 1.0})
    series, ok = metadata.fetch_series("Vagabond")
    assert series["source"] == "mangadex" and series["partial"] is True
    assert metadata.is_stale(series)


def test_result_without_bnf_is_provisional(monkeypatch):
    def bnf_fail(name, **k):
        raise bnf.BnfError("timeout")
    monkeypatch.setattr(bnf, "search_series", bnf_fail)
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: {
        "authors": ["Oda"], "country": "JP", "match_score": 1.0})
    series, ok = metadata.fetch_series("One Piece")
    assert series["source"] == "anilist" and series["partial"] is True


def test_fallback_after_anilist_answered_is_final(monkeypatch):
    monkeypatch.setattr(anilist, "search_series", lambda name, **k: None)
    monkeypatch.setattr(mangadex, "search_series",
                        lambda name, **k: {"authors": ["Toan"], "country": "FR", "match_score": 1.0})
    series, ok = metadata.fetch_series("Run to Heaven")
    assert "partial" not in series and not metadata.is_stale(series)


def test_volume_year_lookup():
    series = {"volume_years": {"1": 2000, "12": 2003}}
    assert metadata.volume_year(series, 12) == 2003
    assert metadata.volume_year(series, 12.0) == 2003
    assert metadata.volume_year(series, 12.5) is None
    assert metadata.volume_year(series, None) is None
    assert metadata.volume_year({}, 1) is None
