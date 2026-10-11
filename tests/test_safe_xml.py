import xml.etree.ElementTree as ET

import pytest

from beheread.infra import safe_xml

BOMB = ('<?xml version="1.0" encoding="UTF-16"?>\n'
        '<!DOCTYPE r [ <!ENTITY a "x"> <!ENTITY b "&a;&a;&a;"> ]>\n'
        '<ComicInfo><Series>&b;</Series></ComicInfo>')


def test_plain_document_is_parsed():
    root = safe_xml.fromstring(b'<?xml version="1.0"?><ComicInfo><Series>Naruto</Series></ComicInfo>')
    assert root.find("Series").text == "Naruto"


def test_utf16_document_is_parsed():
    xml = '<?xml version="1.0" encoding="UTF-16"?><ComicInfo><Series>Naruto</Series></ComicInfo>'
    assert safe_xml.fromstring(xml.encode("utf-16")).find("Series").text == "Naruto"


@pytest.mark.parametrize("declared, codec", [("UTF-8", "utf-8"), ("UTF-16", "utf-16"),
                                             ("UTF-16LE", "utf-16-le"),
                                             ("UTF-16BE", "utf-16-be")])
def test_doctype_is_refused_whatever_the_encoding(declared, codec):
    """La recherche de « <!DOCTYPE » dans les octets bruts ne voyait pas un
    document encode en UTF-16."""
    data = BOMB.replace("UTF-16", declared).encode(codec)
    with pytest.raises(safe_xml.UnsafeXmlError):
        safe_xml.fromstring(data)


def test_encoding_unknown_to_expat_raises_parse_error():
    xml = '<?xml version="1.0" encoding="UTF-16-LE"?><x/>'.encode("utf-16-le")
    with pytest.raises(ET.ParseError):
        safe_xml.fromstring(b"\xff\xfe" + xml)


def test_external_doctype_is_refused():
    with pytest.raises(safe_xml.UnsafeXmlError):
        safe_xml.fromstring(b'<!DOCTYPE x SYSTEM "file:///etc/passwd"><x/>')


def test_malformed_document_raises_parse_error():
    with pytest.raises(ET.ParseError):
        safe_xml.fromstring(b"<ComicInfo><Series>")
