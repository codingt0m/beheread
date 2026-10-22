"""Tests du client Wikidata (reponses de l'API simulees, aucun acces reseau) :
nature de l'oeuvre d'apres P31 et le pays d'origine, homonymes."""

import pytest

from beheread.infra import wikidata


def _entity(qid, label, classes, country=None, authors=(), parts=None, start=None, aliases=()):
    def item(prop, value):
        return {"mainsnak": {"datavalue": {"value": {"id": value}}}}
    claims = {"P31": [item("P31", c) for c in classes]}
    if country:
        claims["P495"] = [item("P495", country)]
    if authors:
        claims["P50"] = [item("P50", a) for a in authors]
    if parts is not None:
        claims["P2635"] = [{"mainsnak": {"datavalue": {"value": {"amount": f"+{parts}"}}}}]
    if start:
        claims["P580"] = [{"mainsnak": {"datavalue": {"value": {"time": f"+{start}-00-00T00:00:00Z"}}}}]
    return {"id": qid, "labels": {"fr": {"value": label}},
            "aliases": {"en": [{"value": a} for a in aliases]}, "claims": claims}


def _serve(monkeypatch, entities, people=None):
    calls = []

    def get(params):
        calls.append(params)
        if params.get("list") == "search":
            return {"query": {"search": [{"title": e["id"]} for e in entities]}}
        if params.get("props") == "labels":
            return {"entities": {q: {"labels": {"fr": {"value": name}}}
                                 for q, name in (people or {}).items()}}
        return {"entities": {e["id"]: e for e in entities}}
    monkeypatch.setattr(wikidata, "_get", get)
    return calls


def test_comics_series(monkeypatch):
    calls = _serve(monkeypatch, [
        _entity("Q1638157", "Invincible", ["Q14406742"], "Q30", ["Q1"], start="2003"),
        _entity("Q2", "Invincible", ["Q117467246"], "Q30")],   # serie animee : pas une BD
        people={"Q1": "Robert Kirkman"})
    r = wikidata.search_series("Invincible")
    assert r["kind"] == "comics" and r["format"] == "bd" and r["country"] == "US"
    assert r["authors"] == ["Robert Kirkman"] and r["published_year"] == 2003
    assert r["kinds"] == ["comics"]
    assert "haswbstatement:" in calls[0]["srsearch"]


def test_manga_and_manfra_read_right_to_left(monkeypatch):
    _serve(monkeypatch, [_entity("Q21015266", "Radiant", ["Q3285662"], "Q142", parts=19)])
    r = wikidata.search_series("Radiant")
    assert r["kind"] == "manga" and r["format"] == "manga" and r["volumes"] == 19


def test_manhwa_reads_left_to_right(monkeypatch):
    _serve(monkeypatch, [_entity("Q1", "Solo Leveling", ["Q74262765"], "Q884")])
    r = wikidata.search_series("Solo Leveling")
    assert r["kind"] == "manhwa" and r["format"] == "bd" and r["country"] == "KR"


def test_homonyms_are_all_reported(monkeypatch):
    _serve(monkeypatch, [_entity("Q1", "Invincible", ["Q14406742"], "Q30"),
                         _entity("Q2", "Invincible", ["Q21198342"], "Q17")])
    assert wikidata.search_series("Invincible")["kinds"] == ["comics", "manga"]


def test_author_hint_breaks_ties(monkeypatch):
    _serve(monkeypatch, [_entity("Q1", "Monster", ["Q21198342"], "Q884", ["Q10"]),
                         _entity("Q2", "Monster", ["Q21198342"], "Q17", ["Q11"])],
           people={"Q10": "Kim Hyun", "Q11": "Naoki Urasawa"})
    assert wikidata.search_series("Monster", ["Urasawa"])["wikidata_id"] == "Q2"


def test_unrelated_titles_and_empty_results(monkeypatch):
    _serve(monkeypatch, [_entity("Q1", "Saga Valta", ["Q14406742"])])
    assert wikidata.search_series("Saga") is None
    _serve(monkeypatch, [])
    assert wikidata.search_series("Saga") is None
    assert wikidata.search_series("") is None


def test_ambiguous_number_of_parts_is_ignored(monkeypatch):
    e = _entity("Q1", "Vinland Saga", ["Q21198342"], "Q17", parts=29)
    e["claims"]["P2635"].append({"mainsnak": {"datavalue": {"value": {"amount": "+220"}}}})
    _serve(monkeypatch, [e])
    assert wikidata.search_series("Vinland Saga")["volumes"] is None


def test_network_error_raises(monkeypatch):
    def fail(req, timeout=None):
        raise OSError("hors ligne")
    monkeypatch.setattr(wikidata, "_throttle", lambda: None)
    monkeypatch.setattr(wikidata.urllib.request, "urlopen", fail)
    with pytest.raises(wikidata.WikidataError):
        wikidata.search_series("Saga")
