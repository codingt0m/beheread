"""Analyse de XML non fiable (ComicInfo.xml d'une archive telechargee,
reponses de la BnF) : tout document qui declare un DOCTYPE est refuse.

Un DOCTYPE est le prerequis des attaques XML classiques (expansion d'entites
facon « billion laughs », XXE), et ni ComicInfo.xml ni les reponses SRU n'en
ont besoin. Le controle est fait par expat lui-meme, avant toute expansion
d'entite : chercher la sequence « <!DOCTYPE » dans les octets bruts se
contournait en encodant le document en UTF-16.
"""

import xml.etree.ElementTree as ET
from xml.parsers import expat


class UnsafeXmlError(ValueError):
    """Document refuse : il declare un DOCTYPE."""


def fromstring(data: bytes) -> ET.Element:
    """Comme ET.fromstring, mais leve UnsafeXmlError si le document declare
    un DOCTYPE (ET.ParseError s'il est mal forme)."""
    _reject_doctype(data)
    try:
        return ET.fromstring(data)
    except ValueError as e:   # encodage declare inconnu d'expat (« UTF-16-LE »...)
        raise ET.ParseError(str(e)) from e


def _reject_doctype(data: bytes):
    def refuse(*_args):
        raise UnsafeXmlError("DOCTYPE refusé")

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    try:
        parser.Parse(data, True)
    except UnsafeXmlError:
        raise
    except (expat.ExpatError, ValueError):
        pass   # mal forme ou illisible : ET.fromstring le signale (ParseError)
