"""Tests du client du catalogue de la BnF (reponses SRU simulees, aucun acces
reseau) : titre de serie, auteur, et nature BD / manga d'apres le format."""

import io

import pytest

from beheread.infra import bnf


def _record(title, creator, publisher, date, fmt, description="", kind="texte imprimé"):
    desc = f"<dc:description>{description}</dc:description>" if description else ""
    return f"""<srw:record><srw:recordData>
<oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
           xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>{title}</dc:title><dc:creator>{creator}</dc:creator>
  <dc:publisher>{publisher}</dc:publisher><dc:date>{date}</dc:date>
  <dc:format>{fmt}</dc:format>{desc}<dc:type xml:lang="fre">{kind}</dc:type>
</oai_dc:dc></srw:recordData></srw:record>"""


def _response(*records):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">'
            f"<srw:records>{''.join(records)}</srw:records>"
            "</srw:searchRetrieveResponse>").encode("utf-8")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(bnf, "_throttle", lambda: None)


def _serve(monkeypatch, body, captured=None):
    def urlopen(req, timeout=None):
        if captured is not None:
            captured.append(req.full_url)
        return _Resp(body)
    monkeypatch.setattr(bnf.urllib.request, "urlopen", urlopen)


def test_series_title_and_author_parsing():
    assert bnf.series_title("Lou ! Sonata. 2 / Julien Neel") == "Lou ! Sonata"
    assert bnf.series_title("Seuls : intégrale du cycle 2 / Gazzotti, Vehlmann") == "Seuls"
    assert bnf.series_title("Seuls. Intégrale du cycle 1 / [dessin de] Gazzotti") == "Seuls"
    assert bnf.author_name("Neel, Julien (1976-....). Auteur du texte") == "Julien Neel"
    assert bnf.author_name("Oda, Eiichirō (1975-....)") == "Eiichirō Oda"
    assert bnf.author_name("Mousko. Interprète") == "Mousko"


def test_classify_by_size_collection_and_publisher():
    assert bnf.classify("1 vol. (56 p.) : ill. en coul. ; 30 cm") == "bd"
    assert bnf.classify("1 vol. (208 p.) : illustrations en noir et blanc ; 18 x 12 cm") == "manga"
    assert bnf.classify("1 vol. (168 p.) ; 22 cm", ["Collection : Seinen"]) == "manga"
    assert bnf.classify("1 vol. ; 22 cm", publisher="Ki-oon (Paris)") == "manga"
    assert bnf.classify("1 vol. ; 22 cm", publisher="Dupuis (Marcinelle)") is None


def test_search_finds_bande_dessinee(monkeypatch):
    captured = []
    _serve(monkeypatch, _response(
        _record("Lou ! Sonata. 2 / Julien Neel", "Neel, Julien (1976-....). Auteur du texte",
                "Glénat (Grenoble)", "2023", "1 vol. ([135] p.) : ill. en coul. ; 27 cm"),
        _record("Lou ! Sonata. [1] / Julien Neel", "Neel, Julien (1976-....). Auteur du texte",
                "Glénat (Grenoble)", "2020", "1 vol. ([132] p.) : ill. en coul. ; 27 cm"),
        _record("Lou ! / Mousko", "Mousko. Interprète", "Universal", "2025", "",
                kind="enregistrement sonore")), captured)
    r = bnf.search_series("Lou ! Sonata")
    assert r["authors"] == ["Julien Neel"] and r["published_year"] == 2020
    assert r["format"] == "bd" and r["publisher"] == "Glénat"
    assert "Lou+Sonata" in captured[0]   # ponctuation retiree de la requete


def test_search_recognises_translated_manga(monkeypatch):
    _serve(monkeypatch, _response(
        _record("L'atelier des sorciers. 14 / Kamome Shirahama", "Shirahama, Kamome. Auteur du texte",
                "Pika édition (Vanves)", "2025", "1 vol. (168 p.) : ill. ; 18 cm",
                "Collection : Seinen"),
        _record("L'atelier des sorciers. 11 / Kamome Shirahama", "Shirahama, Kamome. Auteur du texte",
                "Pika édition (Vanves)", "2023", "1 vol. (154 p.) : ill. ; 18 cm")))
    assert bnf.search_series("L'Atelier des Sorciers")["format"] == "manga"


def test_search_ignores_longer_unrelated_titles(monkeypatch):
    _serve(monkeypatch, _response(
        _record("Seuls au monde / Jean Dupont", "Dupont, Jean", "Seuil", "1999",
                "1 vol. (300 p.) ; 22 cm")))
    assert bnf.search_series("Seuls") is None


def test_mixed_formats_give_no_reading_hint(monkeypatch):
    """Titre generique : des notices sans rapport se contredisent, aucune
    nature n'est alors retenue (le sens de lecture n'en deduit rien)."""
    _serve(monkeypatch, _response(
        _record("Monster / A", "A, B", "X", "2001", "ill. ; 30 cm"),
        _record("Monster / C", "C, D", "Y", "2002", "ill. ; 18 cm")))
    assert bnf.search_series("Monster")["format"] is None


def test_network_error_raises(monkeypatch):
    def fail(req, timeout=None):
        raise OSError("hors ligne")
    monkeypatch.setattr(bnf.urllib.request, "urlopen", fail)
    with pytest.raises(bnf.BnfError):
        bnf.search_series("Seuls")


def test_doctype_is_refused(monkeypatch):
    _serve(monkeypatch, b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>')
    with pytest.raises(bnf.BnfError):
        bnf.search_series("Seuls")
