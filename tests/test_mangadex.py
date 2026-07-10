"""Tests du client MangaDex : matching de titre (titre principal + titres
alternatifs), nettoyage de l'auteur, conversion langue -> pays, et parsing
d'une reponse d'API complete (couche HTTP mockee, aucun acces reseau reel)."""

import io
import json

import mangadex


def test_title_matches_main_and_alt_titles():
    # match direct sur le titre principal
    assert mangadex._title_matches("One Piece", ["One Piece"])
    # match via un titre alternatif traduit (cas Solo Leveling : titre principal
    # coreen romanise, "Solo Leveling" seulement en titre alternatif)
    assert mangadex._title_matches(
        "Solo Leveling", ["Na Honjaman Level-Up", "Solo Leveling", "I level up alone"])
    # oeuvre sans rapport : rejetee
    assert not mangadex._title_matches("Run to Heaven", ["Berserk", "Kentaro"])
    assert not mangadex._title_matches("", ["Anything"])


def test_clean_author_strips_native_script():
    assert mangadex._clean_author("Oda Eiichirou (尾田栄一郎)") == "Oda Eiichirou"
    assert mangadex._clean_author("DAUL (다울)") == "DAUL"
    assert mangadex._clean_author("Toan") == "Toan"
    assert mangadex._clean_author(None) == ""


def test_main_author_prefers_author_over_artist():
    rels = [
        {"type": "artist", "attributes": {"name": "Some Artist"}},
        {"type": "author", "attributes": {"name": "Real Author"}},
    ]
    assert mangadex._main_author(rels) == ["Real Author"]
    # aucun auteur credite : repli sur l'artiste
    rels_artist_only = [{"type": "artist", "attributes": {"name": "Solo Artist"}}]
    assert mangadex._main_author(rels_artist_only) == ["Solo Artist"]
    assert mangadex._main_author([]) == []


def test_country_of_language_mapping():
    assert mangadex._country_of("ja") == "JP"
    assert mangadex._country_of("ko") == "KR"
    assert mangadex._country_of("zh") == "CN"
    assert mangadex._country_of("zh-hk") == "CN"
    # langue non mappee (ex. francais) : code a deux lettres, presume RTL en aval
    assert mangadex._country_of("fr") == "FR"
    assert mangadex._country_of(None) is None


def _fake_response(payload):
    """Fabrique un context manager facon urlopen renvoyant le JSON donne."""
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
            return False
    return _Resp(json.dumps(payload).encode("utf-8"))


def test_search_series_parses_full_response(monkeypatch):
    """Parsing d'une reponse type "Run to Heaven" : titre, auteur nettoye,
    annee et pays deduit de la langue d'origine."""
    payload = {"data": [{
        "attributes": {
            "title": {"en": "Run to Heaven"},
            "altTitles": [],
            "year": 2024,
            "originalLanguage": "fr",
        },
        "relationships": [
            {"type": "author", "attributes": {"name": "Toan"}},
            {"type": "artist", "attributes": {"name": "Toan"}},
        ],
    }]}
    monkeypatch.setattr(mangadex, "_throttle", lambda: None)
    monkeypatch.setattr(mangadex.urllib.request, "urlopen",
                        lambda *a, **k: _fake_response(payload))

    result = mangadex.search_series("Run to Heaven")
    assert result == {
        "title": "Run to Heaven",
        "authors": ["Toan"],
        "published_year": 2024,
        "country": "FR",
    }


def test_search_series_skips_unrelated_first_result(monkeypatch):
    """MangaDex renvoie parfois un spin-off en tete : on retient le premier
    resultat dont un titre correspond reellement, via ses titres alternatifs."""
    payload = {"data": [
        {"attributes": {"title": {"en": "Solo Leveling: Ragnarok"},
                        "altTitles": [], "year": 2024, "originalLanguage": "ko"},
         "relationships": []},
        {"attributes": {"title": {"en": "Na Honjaman Level-Up"},
                        "altTitles": [{"en": "Solo Leveling"}],
                        "year": 2018, "originalLanguage": "ko"},
         "relationships": [{"type": "author", "attributes": {"name": "Chugong"}}]},
    ]}
    monkeypatch.setattr(mangadex, "_throttle", lambda: None)
    monkeypatch.setattr(mangadex.urllib.request, "urlopen",
                        lambda *a, **k: _fake_response(payload))

    result = mangadex.search_series("Solo Leveling")
    assert result["published_year"] == 2018   # la vraie serie, pas le spin-off
    assert result["authors"] == ["Chugong"]
    assert result["country"] == "KR"


def test_search_series_none_when_no_match(monkeypatch):
    payload = {"data": [
        {"attributes": {"title": {"en": "Something Else"}, "altTitles": [],
                        "year": 2000, "originalLanguage": "ja"},
         "relationships": []},
    ]}
    monkeypatch.setattr(mangadex, "_throttle", lambda: None)
    monkeypatch.setattr(mangadex.urllib.request, "urlopen",
                        lambda *a, **k: _fake_response(payload))
    assert mangadex.search_series("Run to Heaven") is None


def test_search_series_empty_data(monkeypatch):
    monkeypatch.setattr(mangadex, "_throttle", lambda: None)
    monkeypatch.setattr(mangadex.urllib.request, "urlopen",
                        lambda *a, **k: _fake_response({"data": []}))
    assert mangadex.search_series("Whatever") is None
