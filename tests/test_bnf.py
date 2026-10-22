"""Tests du client du catalogue de la BnF (reponses SRU UNIMARC simulees,
aucun acces reseau) : serie et numero de tome, auteur par son role, nature
BD / manga d'apres la langue originale et le format, nombre de tomes parus."""

import io
from xml.sax.saxutils import escape

import pytest

from beheread.infra import bnf


def _field(tag, **subfields):
    subs = "".join(f'<mxc:subfield code="{code.lstrip("_")}">{escape(str(v))}</mxc:subfield>'
                   for code, v in subfields.items() if v is not None)
    return f'<mxc:datafield tag="{tag}" ind1=" " ind2=" ">{subs}</mxc:datafield>'


def _record(title, number=None, series=None, authors=(("Neel", "Julien", "070"),),
            publisher="Glénat", date="2020", height="27 cm", lang="fre", orig=None,
            collection=None, summary=None, isbn=None, leader="     cam  22        450 "):
    fields = [_field("101", a=lang, c=orig), _field("200", a=title,
                                                     h=number if series is None else None),
              _field("210", c=publisher, d=date), _field("215", a="1 vol.", d=height)]
    if series is not None:
        fields.append(_field("461", t=series, v=number))
    if collection:
        fields.append(_field("225", a=collection))
    if summary:
        fields.append(_field("330", a=summary))
    if isbn:
        fields.append(_field("010", a=isbn))
    for last, first, role in authors:
        fields.append(_field("700", a=last, b=first, _4=role))
    return ("<srw:record><srw:recordData>"
            '<mxc:record xmlns:mxc="info:lc/xmlns/marcxchange-v2">'
            f"<mxc:leader>{leader}</mxc:leader>{''.join(fields)}</mxc:record>"
            "</srw:recordData></srw:record>")


def _response(*records, total=None):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/">'
            f"<srw:numberOfRecords>{len(records) if total is None else total}</srw:numberOfRecords>"
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


def _serve(monkeypatch, *bodies, captured=None):
    """Repond successivement `bodies` (le dernier se repete)."""
    queue = list(bodies)

    def urlopen(req, timeout=None):
        if captured is not None:
            captured.append(req.full_url)
        return _Resp(queue.pop(0) if len(queue) > 1 else queue[0])
    monkeypatch.setattr(bnf.urllib.request, "urlopen", urlopen)


def test_volume_numbers():
    assert bnf.volume_number("3") == 3
    assert bnf.volume_number("[2]") == 2
    assert bnf.volume_number("Tome 09") == 9
    assert bnf.volume_number("vol. 2") == 2
    assert bnf.volume_number("7-8") is None          # integrale
    assert bnf.volume_number("intégrale du cycle 2") is None


def test_classify_by_collection_publisher_and_size():
    assert bnf.classify("30 cm") == "bd"
    assert bnf.classify("22 cm", ["Seinen"]) == "manga"
    assert bnf.classify("22 cm", publisher="Ki-oon") == "manga"
    assert bnf.classify("18 cm", forms=["Mangas"]) == "manga"
    assert bnf.classify("18 cm", ["Shônen"]) == "manga"              # accent
    assert bnf.classify("22 cm", ["Combo"], "Dargaud") == "manga"    # label manga de Dargaud
    # un petit format seul n'est pas un manga (BD jeunesse)
    assert bnf.classify("18 cm", publisher="Tourbillon") is None


def test_search_finds_bande_dessinee_with_its_volumes(monkeypatch):
    captured = []
    _serve(monkeypatch, _response(
        _record("Sonata", 2, series="Lou !", date="DL 2023", summary="Retour en mode majeur."),
        _record("Lou !", None, date="2020-"),                       # notice d'ensemble
        _record("Sonata", 1, series="Lou !", date="2020"),
        _record("Lou ! Sonata", 1, series="Lou !", lang="eng", orig="fre", publisher="Europe Comics",
                date="2021", authors=(("Neel", "Julien", "070"), ("Smith", "Ann", "730")))),
        captured=captured)
    r = bnf.search_series("Lou !")
    assert r["authors"] == ["Julien Neel"] and r["published_year"] == 2020
    assert r["format"] == "bd" and r["origin"] == "fre" and r["publisher"] == "Glénat"
    assert r["volumes"] == 2 and r["volume_years"] == {"1": 2020, "2": 2023}
    assert r["description"] == "Retour en mode majeur."   # tome 1 sans resume : le suivant
    assert 'bib.subject all "bandes dessinees"' in bnf.urllib.parse.unquote_plus(captured[0])


def test_translated_comics_are_western_whatever_their_size(monkeypatch):
    _serve(monkeypatch, _response(*(
        _record(f"Tome {n}", n, series="Saga", orig="eng", publisher="Urban comics", height="18 cm",
                authors=(("Vaughan", "Brian K", "070"), ("Staples", "Fiona", "440")),
                date=str(2012 + n)) for n in range(1, 4))))
    r = bnf.search_series("Saga")
    assert r["format"] == "bd" and r["origin"] == "eng" and r["country"] is None
    assert r["authors"] == ["Brian K Vaughan"]
    assert r["creators"] == ["Brian K Vaughan", "Fiona Staples"]
    assert r["volumes"] == 3


def test_translated_manga_is_recognised_by_its_language(monkeypatch):
    _serve(monkeypatch, _response(
        _record("L'atelier des sorciers", 14, orig="jpn", publisher="Pika édition", height="18 cm",
                authors=(("Shirahama", "Kamome", "070"), ("Tamon", "Fédoua", "730"))),
        _record("L'atelier des sorciers", 11, orig="jpn", height="18 cm",
                authors=(("Shirahama", "Kamome", "070"),))))
    r = bnf.search_series("L'Atelier des Sorciers")
    assert r["format"] == "manga" and r["country"] == "JP"
    assert r["authors"] == ["Kamome Shirahama"]   # pas la traductrice


def test_french_small_format_without_manga_hint_is_undecided(monkeypatch):
    _serve(monkeypatch, _response(*(
        _record("Mortelle Adèle", n, height="18 cm", publisher="Tourbillon",
                authors=(("Mr Tan", "", "070"),)) for n in (1, 2))))
    assert bnf.search_series("Mortelle Adele")["format"] is None


def test_sparse_numbers_give_no_volume_count(monkeypatch):
    """Des numeros epars (numeros de revue, autre edition) ne disent pas
    combien de tomes sont parus."""
    _serve(monkeypatch, _response(_record("X", 1, series="Astérix"),
                                  _record("Y", 120, series="Astérix")))
    assert bnf.search_series("Asterix")["volumes"] is None


def test_first_edition_gives_publisher_and_year(monkeypatch):
    _serve(monkeypatch, _response(
        _record("Thorgal", 1, publisher="Le Figaro", date="2010"),
        _record("Thorgal", 2, publisher="Le Figaro", date="2010"),
        _record("Thorgal", 3, publisher="Le Figaro", date="2010"),
        _record("Thorgal", 1, publisher="le Lombard", date="1980"),
        _record("Thorgal", 2, publisher="le Lombard", date="1981"),
        _record("Thorgal", 3, publisher="le Lombard", date="1982")))
    r = bnf.search_series("Thorgal")
    assert r["publisher"] == "le Lombard" and r["published_year"] == 1980
    assert r["volume_years"]["2"] == 1981


def test_author_hint_picks_the_homonym(monkeypatch):
    _serve(monkeypatch, _response(
        _record("Monster", 1, orig="kor", authors=(("Kim", "Hyun", "070"),)),
        _record("Monster", 1, orig="jpn", authors=(("Urasawa", "Naoki", "070"),))))
    r = bnf.search_series("Monster", author_hint=["Urasawa"])
    assert r["authors"] == ["Naoki Urasawa"] and r["format"] == "manga"


def test_search_ignores_longer_unrelated_titles(monkeypatch):
    _serve(monkeypatch, _response(_record("Seuls au monde")), _response())
    assert bnf.search_series("Seuls") is None


def test_fallback_query_keeps_only_comics(monkeypatch):
    """Sans le sujet « bandes dessinees », seules les notices portant un
    indice de BD comptent : les romans homonymes sont ecartes."""
    novel = _record("Largo Winch", 1, height="18 cm", publisher="Mercure de France")
    album = _record("Largo Winch", 1, publisher="Dupuis").replace(
        "</mxc:record>", _field("686", a="805") + "</mxc:record>")
    _serve(monkeypatch, _response(), _response(novel))
    assert bnf.search_series("Largo Winch") is None
    _serve(monkeypatch, _response(), _response(novel, album))
    assert bnf.search_series("Largo Winch")["publisher"] == "Dupuis"


def test_records_that_are_not_books_are_ignored(monkeypatch):
    disc = _record("Lou !", 1, leader="     cjm  22        450 ")      # enregistrement sonore
    serial = _record("Lou !", 1, leader="     cas  22        450 ")    # revue
    _serve(monkeypatch, _response(disc, serial), _response())
    assert bnf.search_series("Lou !") is None


def test_pages_are_fetched_until_the_total(monkeypatch):
    captured = []
    page = _response(*(_record("Thorgal", n) for n in range(1, 3)), total=150)
    _serve(monkeypatch, page, captured=captured)
    bnf.search_series("Thorgal")
    assert len(captured) == 2 and "startRecord=101" in captured[1]


def test_search_isbn(monkeypatch):
    captured = []
    _serve(monkeypatch, _response(_record(
        "Celui qui part", 3, series="Les vieux fourneaux", publisher="Dargaud", date="DL 2015",
        authors=(("Lupano", "Wilfrid", "070"), ("Cauuet", "Paul", "440")),
        summary="Pierrot, Mimile et Antoine...", isbn="978-2-5050-6352-0")), captured=captured)
    r = bnf.search_isbn("978-2-5050-6352-0")
    assert 'bib.isbn all "9782505063520"' in bnf.urllib.parse.unquote_plus(captured[0])
    assert r["series"] == "Les vieux fourneaux" and r["number"] == 3
    assert r["title"] == "Celui qui part" and r["published_year"] == 2015
    assert r["authors"] == ["Wilfrid Lupano"] and r["isbn"] == "9782505063520"
    assert bnf.search_isbn("12") is None


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


def test_dns_failure_falls_back_to_pinned_ip(monkeypatch):
    def unresolved(req, timeout=None):
        raise bnf.urllib.error.URLError(bnf.socket.gaierror(11002, "getaddrinfo failed"))
    monkeypatch.setattr(bnf.urllib.request, "urlopen", unresolved)
    monkeypatch.setattr(bnf, "_open_pinned", lambda req: _Resp(_response(
        _record("100 bullets", 1, authors=(("Azzarello", "Brian", "070"),), orig="eng"))))
    assert bnf.search_series("100 Bullets")["authors"] == ["Brian Azzarello"]


def test_other_network_errors_skip_the_fallback(monkeypatch):
    def refused(req, timeout=None):
        raise bnf.urllib.error.URLError(ConnectionRefusedError())
    monkeypatch.setattr(bnf.urllib.request, "urlopen", refused)
    monkeypatch.setattr(bnf, "_open_pinned", lambda req: pytest.fail("repli inattendu"))
    with pytest.raises(bnf.BnfError):
        bnf.search_series("Seuls")


def test_pinned_connection_keeps_the_hostname(monkeypatch):
    targets = []

    def create_connection(addr, *a, **k):
        targets.append(addr)
        raise OSError("pas de reseau en test")
    monkeypatch.setattr(bnf.socket, "create_connection", create_connection)
    conn = bnf._PinnedConnection("catalogue.bnf.fr")
    with pytest.raises(OSError):
        conn.connect()
    assert targets == [(bnf.FALLBACK_IP, 443)]
    assert conn.host == "catalogue.bnf.fr"   # SNI et certificat verifies sur ce nom
