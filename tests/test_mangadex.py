"""Tests du client MangaDex : matching de titre (titre principal + titres
alternatifs), nettoyage de l'auteur, conversion langue -> pays, et parsing
d'une reponse d'API complete (couche HTTP mockee, aucun acces reseau reel)."""

import io
import json

from beheread.infra import mangadex


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
        "titles": ["Run to Heaven"],
        "authors": ["Toan"],
        "published_year": 2024,
        "country": "FR",
        "description": "",
        "genres": [],
        "volumes": None,
        "match_score": 1.0,
        "mangadex_id": None,
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



def test_author_hint_picks_the_right_homonym(monkeypatch):
    def item(id_, author, lang):
        return {"id": id_, "attributes": {"title": {"en": "Monster"}, "originalLanguage": lang},
                "relationships": [{"type": "author", "attributes": {"name": author}}]}
    payload = {"data": [item("a", "Mo You", "zh"), item("b", "Urasawa Naoki", "ja")]}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(mangadex.urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp(json.dumps(payload).encode()))
    monkeypatch.setattr(mangadex, "_throttle", lambda: None)
    assert mangadex.search_series("Monster", author_hint=["Urasawa"])["country"] == "JP"



def test_search_series_prefers_the_french_summary(monkeypatch):
    payload = {"data": [{
        "attributes": {
            "title": {"en": "Vagabond"}, "altTitles": [], "year": 1998,
            "originalLanguage": "ja", "lastVolume": "37",
            "description": {"en": "Musashi's journey.", "fr": "Le voyage de Musashi."},
            "tags": [{"attributes": {"group": "genre", "name": {"en": "Historical"}}},
                     {"attributes": {"group": "theme", "name": {"en": "Samurai"}}}],
        },
        "relationships": [{"type": "author", "attributes": {"name": "Inoue Takehiko"}}],
    }]}
    monkeypatch.setattr(mangadex, "_throttle", lambda: None)
    monkeypatch.setattr(mangadex.urllib.request, "urlopen",
                        lambda req, timeout=None: _fake_response(payload))
    r = mangadex.search_series("Vagabond")
    assert r["description"] == "Le voyage de Musashi."
    assert r["genres"] == ["Historique"] and r["volumes"] == 37


def test_aggregate_gives_the_chapters_of_each_volume(monkeypatch):
    """Decoupage officiel : premier et dernier chapitre de chaque tome ; les
    chapitres hors tome, les numeros non numeriques, les chapitres egares
    dans un tome et un tome qui chevauche le precedent sont ignores."""
    chapters = lambda *ns: {str(n): {} for n in ns}   # noqa: E731
    payload = {"result": "ok", "volumes": {
        # « 232 » egare dans le tome 1 (cas reel de Chainsaw Man sur MangaDex)
        "1": {"volume": "1", "chapters": chapters(1, 2, 3, 3.5, 232)},
        "2": {"volume": "2", "chapters": chapters(4, 5, 6)},
        "3": {"volume": "3", "chapters": chapters(5, 6)},     # chevauche le 2
        "none": {"volume": "none", "chapters": chapters(233)},
        "bonus": {"volume": "bonus", "chapters": {"x": {}}},
    }}
    seen = []

    def fake_urlopen(req, **_k):
        seen.append(req.full_url)
        return _fake_response(payload)

    monkeypatch.setattr(mangadex, "_throttle", lambda: None)
    monkeypatch.setattr(mangadex.urllib.request, "urlopen", fake_urlopen)
    assert mangadex.chapter_ranges("abc-123") == {"1": [1, 3.5], "2": [4, 6]}
    assert seen == ["https://api.mangadex.org/manga/abc-123/aggregate"]


def test_aggregate_without_volumes():
    assert mangadex.parse_aggregate({"result": "ok", "volumes": []}) == {}
    assert mangadex.parse_aggregate(None) == {}


def test_latest_volume_and_chapter():
    """Dernier tome : le plus grand du decoupage retenu ; dernier chapitre :
    chapitres hors tome compris, sans un egare isole tres loin."""
    chapters = lambda *ns: {str(n): {} for n in ns}   # noqa: E731
    payload = {"volumes": {
        "1": {"chapters": chapters(1, 2, 3)},
        "2": {"chapters": chapters(4, 5, 6)},
        "none": {"chapters": chapters(7, 8, 8.5, 9, 400)},
    }}
    assert mangadex.parse_latest(payload) == (2, 9)
    assert mangadex.parse_latest({"volumes": []}) == (None, None)


def test_cover_prefers_french_then_english_then_japanese():
    def cover(volume, locale, name):
        return {"attributes": {"volume": volume, "locale": locale, "fileName": name}}
    payload = {"data": [cover("23", "ja", "ja23.jpg"), cover("23", "en", "en23.jpg"),
                        cover("22", "fr", "fr22.jpg"), cover("24", "zh", "zh24.jpg")]}
    assert mangadex.pick_cover(payload, 23) == "en23.jpg"
    assert mangadex.pick_cover(payload, 22) == "fr22.jpg"
    assert mangadex.pick_cover(payload, 24) == "zh24.jpg"    # faute de mieux
    assert mangadex.pick_cover(payload, 25) == ""

