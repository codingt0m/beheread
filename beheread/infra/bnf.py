"""Client minimal pour le catalogue general de la BnF (API SRU publique, sans
cle ni authentification).

Source de reference pour la bande dessinee : le depot legal fait que la BnF
catalogue a peu pres tout ce qui est publie en France - BD franco-belge,
comics et mangas traduits compris. AniList et MangaDex ne connaissent que
les mangas (et apparentes) : interroges seuls, ils associent un comics a un
manga homonyme (« Saga », « Batman »). La notice BnF dit au contraire de
quelle langue l'oeuvre est traduite, ce qui la classe sans ambiguite (voir
metadata._search_series_sources).

Les notices sont lues au format UNIMARC, bien plus riche que le Dublin Core :
  - 461 $t / $v (a defaut 225, 200 $h) : titre de la serie et numero du
    tome - le plus grand numero donne le nombre de tomes parus, la date de
    chaque tome sa date de sortie ;
  - 101 $a / $c : langue du texte et langue originale (« fre » traduit de
    « jpn » : un manga ; de « eng » : un comics) ;
  - 700 a 702 $4 : role de chaque auteur (070 auteur, 440 illustrateur,
    730 traducteur...), pour ne pas retenir un traducteur ;
  - 215 $d : format physique (un album de BD fait 24 a 32 cm de haut, un
    manga relie 17 a 21 cm), 225 $a : collection (« Seinen »...) ;
  - 210/214 $c : editeur, 330 $a : resume, 010 $a : ISBN.

La recherche porte sur les notices du sujet « bandes dessinees » (les romans,
disques et films homonymes en sont ecartes) ; a defaut, sur les textes
imprimes portant un indice de BD (classement 803/805, Dewey 741.5, forme
« Bandes dessinees »).
"""

import http.client
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

from beheread.core.series import matches_author
from beheread.core.text import strip_accents
from beheread.infra import net, safe_xml
from beheread.infra.mangadex import title_score

URL = "https://catalogue.bnf.fr/api/SRU"
TIMEOUT = 20
MIN_INTERVAL = 0.5
PAGE_SIZE = 100
MAX_PAGES = 3   # 300 notices : One Piece (plus de 100 tomes) en compte un peu plus de 200
USER_AGENT = net.APP_USER_AGENT

# adresse de catalogue.bnf.fr, utilisee seulement si le DNS ne resout pas le
# nom (constate avec le DNS de Google, 8.8.8.8, en echec sur tout bnf.fr).
# Le certificat reste verifie pour catalogue.bnf.fr : une adresse perimee
# echoue proprement, sans jamais parler a un autre serveur.
FALLBACK_IP = "194.199.8.30"

# ressemblance minimale (0..1) entre le nom cherche et le titre de serie
# d'une notice : la recherche « tous les mots » de la BnF ramene aussi des
# titres plus longs qui les contiennent (« Seuls au monde » pour « Seuls »)
MIN_SCORE = 0.7

# hauteur (cm) a partir de laquelle un livre est un album de BD
BD_MIN_CM = 23

# numeros de tome retenus pour le nombre de tomes parus : au-dela, c'est une
# autre numerotation (numeros de revue, d'episodes) ; et les numeros connus
# doivent couvrir au moins cette part des tomes 1 a N, sans quoi le plus
# grand est celui d'une autre serie ou d'une autre edition
MAX_VOLUME = 300
MIN_VOLUME_DENSITY = 0.5

# langue originale (101 $c, ISO 639-2) -> pays d'origine (sens de lecture)
ORIGIN_COUNTRY = {"jpn": "JP", "kor": "KR", "chi": "CN", "zho": "CN"}
ASIAN_WESTERN_READING = ("kor", "chi", "zho")   # manhwa, manhua : lus gauche -> droite

# collections et editeurs propres au manga (minuscules, sans accents)
_MANGA_COLLECTIONS = re.compile(
    r"(?i)\b(?:seinen|shonen|shounen|shojo|shoujo|josei|kodomo|manga)\b")
# labels manga d'editeurs generalistes, reconnus a leur nom exact (« Combo »
# de Dargaud : mangas d'auteurs francais, comme « Yon »)
_MANGA_LABELS = {"combo"}
_MANGA_PUBLISHERS = ("kana", "ki-oon", "pika", "kurokawa", "akata", "tonkam", "kaze",
                     "doki-doki", "mangetsu", "noeve", "meian", "vega", "ototo",
                     "taifu", "komikku", "nobi nobi", "crunchyroll", "panini manga",
                     "soleil manga", "glenat manga", "delcourt manga", "kotoji")
_MANGA_FORMS = ("manga",)
# indices de BD d'une notice hors du sujet « bandes dessinees »
_COMIC_CLASSES = ("803", "805")
_COMIC_FORMS = ("bandes dessinees", "romans graphiques", "comics", "mangas")

# roles (700-702 $4) d'un auteur de l'oeuvre : auteur, illustrateur, ou non
# precise ; les traducteurs, prefaciers, coloristes... ne le sont pas
_AUTHOR_ROLES = ("070", "")
_ARTIST_ROLES = ("440",)

_MARC = "{info:lc/xmlns/marcxchange-v2}"
_SRW = "{http://www.loc.gov/zing/srw/}"
_HEIGHT = re.compile(r"(\d+)\s*(?:x\s*\d+\s*)?cm\b")
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
_NUMBER = re.compile(r"(?i)^\[?\s*(?:t(?:ome)?|vol(?:ume)?|n[°o]|livre)?\.?\s*0*(\d{1,3})\s*\]?\.?$")
# caracteres de non-tri (article ignore au classement : « Les » de « Les Vieux
# Fourneaux »), parfois laisses dans les sous-zones
_NON_SORTING = dict.fromkeys(map(ord, "\x88\x89\x98\x9c"))

_LIMITER = net.RateLimiter(MIN_INTERVAL)


class BnfError(Exception):
    """Erreur reseau/HTTP/format - a distinguer d'une recherche sans resultat."""


def _throttle():
    """Espace les requetes vers ce service (voir net.RateLimiter)."""
    _LIMITER.wait()


class _PinnedConnection(http.client.HTTPSConnection):
    """Connexion HTTPS vers FALLBACK_IP, mais SNI, en-tete Host et
    verification du certificat restent ceux du nom demande."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = self._connect_pinned

    @staticmethod
    def _connect_pinned(address, *args, **kwargs):
        return socket.create_connection((FALLBACK_IP, address[1]), *args, **kwargs)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedConnection, req, context=self._context)


def _open_pinned(req):
    return urllib.request.build_opener(_PinnedHTTPSHandler()).open(req, timeout=TIMEOUT)


def _fetch(req) -> bytes:
    """Corps de la reponse ; si le nom ne se resout pas, nouvel essai
    directement sur FALLBACK_IP."""
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.URLError as e:
        if not isinstance(e.reason, socket.gaierror):
            raise
    with _open_pinned(req) as resp:
        return resp.read()


def _fold(text: str) -> str:
    return strip_accents(text or "").casefold()


def _clean(text) -> str:
    """Sous-zone sans caracteres de non-tri ni ponctuation finale (« Largo
    Winch. », « [Gallimard] »)."""
    text = (text or "").translate(_NON_SORTING).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text.strip(" .,:;/").strip()


def volume_number(text):
    """Numero de tome d'une sous-zone (« 3 », « [2] », « Tome 9 », « vol. 2 »),
    ou None : les intervalles (« 7-8 », integrales) et les mentions
    (« intégrale du cycle 2 ») n'en sont pas."""
    m = _NUMBER.match(_clean(text))
    return int(m.group(1)) if m else None


def classify(fmt: str, collections=(), publisher: str = "", forms=()):
    """"bd", "manga" ou None d'apres la collection (« Seinen »), la forme
    (608 « Mangas »), l'editeur (label manga connu) et le format physique
    d'une notice. Seul un album (BD_MIN_CM et plus) se reconnait a sa
    taille : le petit format d'un manga est aussi celui de nombreuses BD
    jeunesse (« Mortelle Adèle »)."""
    if any(_MANGA_COLLECTIONS.search(_fold(c)) or _fold(c) in _MANGA_LABELS
           for c in collections) or \
            any(f in _fold(form) for form in forms for f in _MANGA_FORMS) or \
            any(p in _fold(publisher) for p in _MANGA_PUBLISHERS):
        return "manga"
    m = _HEIGHT.search(fmt or "")
    if m and int(m.group(1)) >= BD_MIN_CM:
        return "bd"
    return None


def _subfields(rec):
    """{zone: [{code: [valeurs]}]} d'une notice UNIMARC, plus "leader"."""
    fields = {}
    leader = rec.find(_MARC + "leader")
    fields["leader"] = leader.text if leader is not None and leader.text else ""
    for df in rec.iter(_MARC + "datafield"):
        sub = {}
        for s in df:
            if s.text and s.text.strip():
                sub.setdefault(s.get("code"), []).append(s.text.strip())
        fields.setdefault(df.get("tag"), []).append(sub)
    return fields


def _first(fields, tag, code):
    for sub in fields.get(tag) or ():
        if sub.get(code):
            return sub[code][0]
    return None


def _person(sub) -> str:
    """« Van Hamme » + « Jean » -> « Jean Van Hamme »."""
    last, first = _clean((sub.get("a") or [""])[0]), _clean((sub.get("b") or [""])[0])
    return f"{first} {last}".strip()


def _notice(fields):
    """Notice simplifiee : titres de serie candidats [(titre, numero)],
    langues, auteurs [(nom, role)], date, format, editeur, collections,
    formes, resume, ISBN ; None pour ce qui n'est pas un texte imprime en un
    volume (disque, video, revue)."""
    leader = fields.get("leader") or ""
    if len(leader) > 7 and (leader[6] != "a" or leader[7] == "s"):
        return None   # 6 : texte ; 7 : « s » = periodique (revue de kiosque)
    def pairs(tag, title_code, number_code):
        return [(_clean(sub[title_code][0]), volume_number((sub.get(number_code) or [""])[0]))
                for sub in fields.get(tag) or () if sub.get(title_code)]
    linked, own, series = pairs("461", "t", "v"), pairs("200", "a", "h"), pairs("225", "a", "v")
    titles = linked + own + series
    authors = []
    for tag in ("700", "701", "702"):
        for sub in fields.get(tag) or ():
            name = _person(sub)
            if name:
                authors.append((name, (sub.get("4") or [""])[0]))
    date = _first(fields, "210", "d") or _first(fields, "214", "d") or ""
    year = _YEAR.search(date)
    if not year:   # 100 $a, positions 9-12 : date codee
        coded = _first(fields, "100", "a") or ""
        year = _YEAR.search(coded[9:13])
    forms = [x for sub in fields.get("608") or () for x in sub.get("a") or ()]
    isbn = re.sub(r"[^\dX]", "", (_first(fields, "010", "a") or "").upper())
    return {
        "titles": [t for t in titles if t[0]],
        "linked": [t for t in linked if t[0]],
        "own": next((t for t in own if t[0]), None),
        "lang": _first(fields, "101", "a"),
        "orig": _first(fields, "101", "c"),
        "country": _first(fields, "102", "a"),
        "authors": authors,
        "year": int(year.group(1)) if year else None,
        "format": _first(fields, "215", "d") or "",
        "publisher": re.sub(r"\s*\(.*$", "", _clean(_first(fields, "210", "c")
                                                    or _first(fields, "214", "c"))),
        "collections": [title for title, _num in series],
        "forms": forms,
        "classes": [x for sub in fields.get("686") or () for x in sub.get("a") or ()],
        "dewey": [x for sub in fields.get("676") or () for x in sub.get("a") or ()],
        "summary": _first(fields, "330", "a") or "",
        "isbn": isbn if len(isbn) in (10, 13) else "",
    }


def _is_comic(notice) -> bool:
    """Indice de BD hors du sujet « bandes dessinees » (requete de repli)."""
    return (any(c.strip() in _COMIC_CLASSES for c in notice["classes"])
            or any(d.startswith("741.5") for d in notice["dewey"])
            or any(f in _fold(form) for form in notice["forms"] for f in _COMIC_FORMS))


def _records(xml: bytes):
    """(notices, nombre total de resultats) d'une reponse SRU."""
    try:
        root = safe_xml.fromstring(xml)
    except safe_xml.UnsafeXmlError as e:
        raise BnfError("reponse refusee (DOCTYPE)") from e
    except ET.ParseError as e:
        raise BnfError(f"reponse illisible : {e}") from e
    total = root.find(_SRW + "numberOfRecords")
    try:
        total = int(total.text) if total is not None else 0
    except (TypeError, ValueError):
        total = 0
    notices = [_notice(_subfields(rec)) for rec in root.iter(_MARC + "record")]
    return [n for n in notices if n is not None], total


def _search(query: str, max_pages: int = MAX_PAGES):
    """Notices repondant a la requete CQL `query`, page par page."""
    notices, start = [], 1
    for _page in range(max_pages):
        params = {"version": "1.2", "operation": "searchRetrieve", "query": query,
                  "recordSchema": "unimarcxchange", "maximumRecords": str(PAGE_SIZE),
                  "startRecord": str(start)}
        url = f"{URL}?{urllib.parse.urlencode(params)}"
        _throttle()
        try:
            xml = _fetch(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _LIMITER.back_off(net.retry_after(e))
            raise BnfError(str(e)) from e
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
            raise BnfError(str(e)) from e
        page, total = _records(xml)
        notices += page
        start += PAGE_SIZE
        if start > total:
            break
    return notices


def _words(name: str) -> str:
    return " ".join(re.sub(r"[^\w\s'-]", " ", strip_accents(name or ""),
                           flags=re.UNICODE).split())


def _majority(counter, share=2 / 3):
    """Valeur qui represente au moins `share` des votes, ou None."""
    if not counter:
        return None
    value, votes = counter.most_common(1)[0]
    return value if votes >= share * sum(counter.values()) else None


def _origin(notices):
    """Langue originale de l'oeuvre (« jpn », « eng »... ; « fre » pour une
    oeuvre francophone non traduite), ou None si les notices se contredisent."""
    votes = Counter(n["orig"] or n["lang"] for n in notices if n["orig"] or n["lang"])
    return _majority(votes)


def _format(notices, origin):
    """"manga" (droite -> gauche) ou "bd" (gauche -> droite) ; None si rien
    de sur. La langue originale decide : traduit du japonais, c'est un
    manga ; d'une autre langue (anglais, coreen, chinois...), un sens
    occidental. Pour une oeuvre francaise, collection, editeur et format
    votent (voir classify) : la nature retenue doit l'emporter aux deux
    tiers et concerner au moins la moitie des notices - quelques albums
    grand format (art-book, coffret) ne font pas d'une serie de mangas
    francais une BD."""
    if origin == "jpn":
        return "manga"
    if origin and origin != "fre":
        return "bd"
    votes = Counter(kind for n in notices
                    if (kind := classify(n["format"], n["collections"], n["publisher"],
                                         n["forms"])))
    kind = _majority(votes)
    return kind if kind and 2 * votes[kind] >= len(notices) else None


def _country(notices, origin):
    if origin in ORIGIN_COUNTRY:
        return ORIGIN_COUNTRY[origin]
    if origin == "fre":
        return _majority(Counter(n["country"] for n in notices if n["country"]), 0.5)
    return None


def _main_author(notices):
    """Auteur le plus cite (role d'auteur, sinon d'illustrateur)."""
    for roles in (_AUTHOR_ROLES, _ARTIST_ROLES):
        names = Counter(name for n in notices for name, role in n["authors"] if role in roles)
        if names:
            return names.most_common(1)[0][0]
    return None


def _creators(notices, limit=6):
    """Auteurs et illustrateurs de la serie, les plus cites d'abord : pour
    reconnaitre la meme oeuvre dans une autre base, qui peut ne citer que
    le scenariste (ou que le dessinateur)."""
    names = Counter(name for n in notices for name, role in n["authors"]
                    if role in _AUTHOR_ROLES + _ARTIST_ROLES)
    return [name for name, _count in names.most_common(limit)]


def _series_of(notice, name):
    """(score, titre de serie, numero) du titre de la notice le plus proche
    du nom cherche."""
    best = (0.0, None, None)
    for title, number in notice["titles"]:
        score = title_score(strip_accents(name), [strip_accents(title)])
        if score > best[0]:
            best = (score, title, number)
    return best


def _volume_count(years):
    """Nombre de tomes parus d'apres les numeros connus, ou None si ces
    numeros sont trop epars pour etre ceux d'une seule serie."""
    numbers = [n for n in years if 1 <= n <= MAX_VOLUME]
    if len(numbers) < 2:
        return None
    last = max(numbers)
    return last if len(numbers) >= MIN_VOLUME_DENSITY * last else None


def summarize(notices, name, author_hint=None):
    """Synthese, pour la serie `name`, de notices deja lues : {title, titles,
    authors, creators, published_year, publisher, format, country, origin, volumes,
    volume_years, description, match_score} ou None si aucune ne correspond.

    Les notices sont regroupees par titre de serie : le groupe retenu est le
    plus ressemblant au nom cherche (a ressemblance egale : celui dont un
    auteur correspond a l'indice tire du nom de fichier, puis le plus fourni).
    Seules ses notices en francais comptent quand il y en a (une edition
    anglaise ou bretonne n'a ni la numerotation ni l'editeur francais)."""
    groups = {}
    for n in notices:
        score, title, number = _series_of(n, name)
        if score < MIN_SCORE:
            continue
        group = groups.setdefault(_fold(title), {"score": 0.0, "items": [], "titles": Counter()})
        group["score"] = max(group["score"], score)
        group["items"].append((n, number))
        group["titles"][title] += 1
    if not groups:
        return None

    def rank(group):
        names = [a for n, _num in group["items"] for a, _role in n["authors"]]
        return (round(group["score"], 2), matches_author(author_hint, names), len(group["items"]))
    group = max(groups.values(), key=rank)
    items = [(n, num) for n, num in group["items"] if n["lang"] == "fre"] or group["items"]
    if author_hint:
        hinted = [(n, num) for n, num in items
                  if matches_author(author_hint, [a for a, _r in n["authors"]])]
        items = hinted or items
    notices = [n for n, _num in items]

    # premiere edition de chaque tome : sa date, son editeur (les reeditions
    # en collection de presse ou de club ne priment pas sur l'editeur d'origine)
    first_editions = {}
    for n, num in items:
        if num is not None and n["year"] and (
                num not in first_editions or n["year"] < first_editions[num]["year"]):
            first_editions[num] = n
    volume_years = {num: n["year"] for num, n in first_editions.items()}
    years = [n["year"] for n in notices if n["year"]]
    origin = _origin(notices)
    author = _main_author(notices)
    publishers = Counter(n["publisher"] for n in (first_editions.values() or notices)
                         if n["publisher"])
    title = group["titles"].most_common(1)[0][0]
    return {"title": title, "titles": list(group["titles"]),
            "authors": [author] if author else [],
            "creators": _creators(notices),
            "published_year": min(years) if years else None,
            "publisher": publishers.most_common(1)[0][0] if publishers else None,
            "format": _format(notices, origin),
            "country": _country(notices, origin),
            "origin": origin,
            "volumes": _volume_count(volume_years),
            "volume_years": {str(k): v for k, v in sorted(volume_years.items())},
            "description": _series_summary(items),
            "match_score": round(group["score"], 3)}


# resumes d'une edition particuliere (integrale, coffret, art-book), qui ne
# presentent pas l'histoire
_NOT_A_STORY = re.compile(r"(?i)int[ée]grale|coffret|art-?book|recueil|r[ée]unit|rassembl|"
                          r"collection|premi[èe]res aventures|cette s[ée]rie")


def _series_summary(items) -> str:
    """Resume de la serie : celui du premier tome (sa premiere edition qui en
    a un), comme Kavita, a defaut celui du plus petit numero."""
    summaries = sorted((num, n["year"] or 9999, n["summary"]) for n, num in items
                       if num is not None and n["summary"]
                       and not _NOT_A_STORY.search(n["summary"]))
    return summaries[0][2] if summaries else ""


def search_series(name: str, author_hint=None):
    """Cherche une serie par son nom (voir summarize pour le resultat), ou
    None si introuvable. Leve BnfError en cas de probleme reseau/HTTP/format."""
    words = _words(name)
    if not words:
        return None
    notices = _search(f'bib.title all "{words}" and bib.subject all "bandes dessinees"')
    found = summarize(notices, name, author_hint)
    if found is not None:
        return found
    # notices sans le sujet « bandes dessinees » (anciennes, ou mal indexees) :
    # textes imprimes portant un autre indice de BD
    notices = _search(f'bib.title all "{words}" and bib.doctype any "a"', max_pages=1)
    return summarize([n for n in notices if _is_comic(n)], name, author_hint)


def search_isbn(isbn: str):
    """Tome identifie par son ISBN (10 ou 13 chiffres) : {title (titre du
    tome), series, number, authors, published_year, publisher, format,
    country, origin, description, isbn} ou None. Leve BnfError en cas de
    probleme reseau/HTTP/format."""
    digits = re.sub(r"[^\dX]", "", (isbn or "").upper())
    if len(digits) not in (10, 13):
        return None
    notices = _search(f'bib.isbn all "{digits}"', max_pages=1)
    if not notices:
        return None
    n = notices[0]
    own_title, own_number = n["own"] or (None, None)
    if n["linked"]:   # tome d'une serie (461) : son propre titre est en 200
        series, number = n["linked"][0]
        if number is None:
            number = own_number
        title = own_title or series
    else:             # titre de la serie en 200, numero en $h
        series, number = own_title, own_number
        title = own_title
    origin = n["orig"] or n["lang"]
    author = _main_author([n])
    return {"title": title, "series": series, "number": number,
            "authors": [author] if author else [],
            "published_year": n["year"], "publisher": n["publisher"] or None,
            "format": _format([n], origin), "country": _country([n], origin),
            "origin": origin, "description": n["summary"], "isbn": n["isbn"] or digits}
