"""Client minimal pour le catalogue general de la BnF (API SRU publique, sans
cle ni authentification).

Dernier recours de la cascade de metadonnees au niveau de la SERIE : AniList
et MangaDex ne connaissent que les mangas (et apparentes), et Google Books,
seul autre catalogue a couvrir la bande dessinee franco-belge, refuse vite
les requetes anonymes (quota partage par adresse IP). Le depot legal fait que
la BnF catalogue a peu pres tout ce qui est publie en France : BD, comics et
mangas traduits compris.

La notice donne aussi le format physique du livre, qui sert d'indice pour le
sens de lecture (voir ui/reader/display.py) : un album de BD fait 24 a 32 cm
de haut, un manga relie 17 a 21 cm. La collection (« Seinen », « Shonen »...)
et l'editeur (labels manga connus) completent cet indice.
"""

import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from beheread.infra.mangadex import title_score

URL = "https://catalogue.bnf.fr/api/SRU"
TIMEOUT = 15
MIN_INTERVAL = 0.5
MAX_RECORDS = 20
USER_AGENT = "Beheread/1.1 (lecteur de BD et mangas)"

# ressemblance minimale (0..1) entre le nom cherche et le titre de serie
# d'une notice : la recherche « tous les mots » de la BnF ramene aussi des
# titres plus longs qui les contiennent (« Seuls au monde » pour « Seuls »)
MIN_SCORE = 0.7

# hauteurs (cm) : album de BD a partir de BD_MIN_CM, manga jusqu'a MANGA_MAX_CM
BD_MIN_CM = 23
MANGA_MAX_CM = 21

# collections et editeurs propres au manga (minuscules, sans accents)
_MANGA_COLLECTIONS = re.compile(
    r"(?i)collection\s*:\s*.*\b(?:seinen|shonen|shounen|shojo|shoujo|josei|kodomo|manga)\b")
_MANGA_PUBLISHERS = ("kana", "ki-oon", "pika", "kurokawa", "akata", "tonkam", "kaze",
                     "doki-doki", "mangetsu", "noeve", "meian", "vega", "ototo",
                     "taifu", "komikku", "nobi nobi", "crunchyroll", "panini manga",
                     "soleil manga", "glenat manga", "delcourt manga", "kotoji")

_NS = {"srw": "http://www.loc.gov/zing/srw/",
       "dc": "http://purl.org/dc/elements/1.1/"}
_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)
_ROLE = re.compile(r"\.\s+(?:Auteur|Illustrateur|Dessinateur|Sc[ée]nariste|Coloriste|"
                   r"Traducteur|Adaptateur|Interpr[èe]te|[ÉE]diteur)\b.*$")
_HEIGHT = re.compile(r"(\d+)\s*(?:x\s*\d+\s*)?cm\b")

_last_request = 0.0
_throttle_lock = threading.Lock()


class BnfError(Exception):
    """Erreur reseau/HTTP/format - a distinguer d'une recherche sans resultat."""


def _throttle():
    global _last_request
    with _throttle_lock:
        elapsed = time.monotonic() - _last_request
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)
        _last_request = time.monotonic()


def _fold(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def series_title(dc_title: str) -> str:
    """Titre de serie d'une notice : avant la mention de responsabilite
    (« / Julien Neel ») et avant le numero ou le titre du tome (« Lou !
    Sonata. 2 », « Seuls : intégrale du cycle 2 »)."""
    main = (dc_title or "").split(" / ")[0]
    return re.split(r"\.\s|\s:\s", main, maxsplit=1)[0].strip(" .:")


def author_name(creator: str) -> str:
    """« Neel, Julien (1976-....). Auteur du texte » -> « Julien Neel »."""
    name = re.sub(r"\s*\([^)]*\)", "", creator or "")
    name = _ROLE.sub("", name).strip(" .")
    if name.count(",") == 1:
        last, first = (part.strip() for part in name.split(","))
        name = f"{first} {last}".strip()
    return name


def classify(fmt: str, descriptions=(), publisher: str = ""):
    """"bd", "manga" ou None d'apres le format physique, la collection et
    l'editeur d'une notice."""
    if any(_MANGA_COLLECTIONS.search(d or "") for d in descriptions):
        return "manga"
    m = _HEIGHT.search(fmt or "")
    if m:
        height = int(m.group(1))
        if height >= BD_MIN_CM:
            return "bd"
        if height <= MANGA_MAX_CM:
            return "manga"
    pub = _fold(publisher)
    if any(p in pub for p in _MANGA_PUBLISHERS):
        return "manga"
    return None


def _query(name: str) -> str:
    words = re.sub(r"[^\w\s'-]", " ", name or "", flags=re.UNICODE).split()
    return 'bib.title all "' + " ".join(words) + '"'


def _records(xml: bytes):
    """Notices Dublin Core d'une reponse SRU : liste de {champ: [valeurs]}."""
    if _DOCTYPE.search(xml):
        raise BnfError("reponse refusee (DOCTYPE)")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise BnfError(f"reponse illisible : {e}") from e
    out = []
    for rec in root.iter("{http://www.openarchives.org/OAI/2.0/oai_dc/}dc"):
        fields = {}
        for el in rec:
            tag = el.tag.rsplit("}", 1)[-1]
            if el.text and el.text.strip():
                fields.setdefault(tag, []).append(el.text.strip())
        out.append(fields)
    return out


def search_series(name: str):
    """Cherche une serie par son nom. Renvoie {title, titles, authors: [str],
    published_year, publisher, format ("bd", "manga" ou None), match_score}
    ou None si introuvable. Leve BnfError en cas de probleme reseau/HTTP/format."""
    params = {"version": "1.2", "operation": "searchRetrieve", "query": _query(name),
              "recordSchema": "dublincore", "maximumRecords": str(MAX_RECORDS)}
    url = f"{URL}?{urllib.parse.urlencode(params)}"
    _throttle()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            xml = resp.read()
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        raise BnfError(str(e)) from e

    matched = []   # (score, notice, titre de serie)
    for rec in _records(xml):
        types = " ".join(rec.get("type", [])).casefold()
        if "texte imprim" not in types and "printed text" not in types:
            continue   # disques, partitions, videos...
        title = series_title((rec.get("title") or [""])[0])
        score = title_score(name, [title])
        if score >= MIN_SCORE:
            matched.append((score, rec, title))
    if not matched:
        return None
    # une BD ou un manga est illustre (« ill. ») : quand le titre est
    # generique (« Monster »), les romans homonymes sont ecartes
    illustrated = [m for m in matched if "ill" in " ".join(m[1].get("format", [])).casefold()]
    matched = illustrated or matched

    best_score, best, title = max(matched, key=lambda m: m[0])
    years = []
    votes = {"bd": 0, "manga": 0}
    for _score, rec, _title in matched:
        for date in rec.get("date", []):
            if re.match(r"\d{4}", date):
                years.append(int(date[:4]))
        kind = classify((rec.get("format") or [""])[0], rec.get("description", []),
                        (rec.get("publisher") or [""])[0])
        if kind:
            votes[kind] += 1
    # nature retenue seulement si les notices concordent nettement (deux
    # tiers) : un titre generique melange des ouvrages sans rapport
    fmt = None
    for kind, other in (("bd", "manga"), ("manga", "bd")):
        if votes[kind] and votes[kind] >= 2 * votes[other]:
            fmt = kind
    creators = [author_name(c) for c in best.get("creator", [])]
    publisher = re.sub(r"\s*\(.*$", "", (best.get("publisher") or [""])[0]).strip()
    return {"title": title, "titles": [title],
            "authors": [c for c in creators if c][:1],
            "published_year": min(years) if years else None,
            "publisher": publisher or None, "format": fmt,
            "match_score": round(best_score, 3)}
