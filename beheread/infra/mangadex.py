"""Client minimal pour l'API MangaDex (publique, sans cle ni authentification).

Utilisee comme filet de securite le plus large pour retrouver les metadonnees
d'une SERIE : le catalogue de MangaDex couvre enormement d'oeuvres de niche
(scans, series independantes ou francaises, webtoons...) la ou AniList et
Google Books restent muets sur les titres peu connus. C'est donc le dernier
recours de la cascade, celui qui permet a un maximum de fichiers d'obtenir
tout de meme un auteur et une annee.

Deux specificites techniques :

* Contrairement a AniList, l'API REFUSE (HTTP 400) un User-Agent de navigateur
  et attend un identifiant applicatif - d'ou l'UA "Beheread" ci-dessous.
* Elle expose la langue d'origine de l'oeuvre (originalLanguage), convertie ici
  en code pays facon AniList (countryOfOrigin) sous la cle "country", pour
  alimenter la detection automatique du sens de lecture (voir ui/reader/display.py).
"""

import difflib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from beheread.core.series import matches_author
from beheread.core.text import clean_description, genre_fr
from beheread.infra import net

BASE_URL = "https://api.mangadex.org/manga"
TIMEOUT = 10
MIN_INTERVAL = 0.3
# MangaDex bloque les UA de navigateur : un identifiant applicatif est attendu.
USER_AGENT = net.APP_USER_AGENT

# langue d'origine (originalLanguage) -> code pays facon AniList, pour un sens
# de lecture coherent : japonais -> Japon (droite->gauche), coreen/chinois ->
# Coree/Chine (manhwa/manhua, gauche->droite). Les autres langues (fr, en...)
# sont converties telles quelles en code a deux lettres : une serie presente
# dans le catalogue manga de MangaDex est presumee lue droite->gauche sauf
# manhwa/manhua (cf. reader._detect_manga_mode).
_LANG_COUNTRY = {"ja": "JP", "ko": "KR", "zh": "CN", "zh-hk": "CN", "zh-ro": "CN"}

_PAREN_SUFFIX = re.compile(r"\s*[\(（][^)）]*[\)）]\s*$")

# score de similarite minimal (0..1) pour retenir un resultat : en dessous, on
# considere que MangaDex n'a pas la bonne serie (evite un auteur/date faux).
_MIN_SCORE = 0.5

_LIMITER = net.RateLimiter(MIN_INTERVAL)


class MangaDexError(Exception):
    """Erreur reseau/HTTP/format - a distinguer d'une recherche sans resultat."""


def _throttle():
    """Espace les requetes vers ce service (voir net.RateLimiter)."""
    _LIMITER.wait()


def _norm_tokens(text: str):
    """Jeu de tokens alphanumeriques en minuscules d'un titre/nom de serie."""
    return set(re.findall(r"\w+", (text or "").casefold(), flags=re.UNICODE))


def _title_score(series_name: str, titles) -> float:
    """Meilleure similarite (0..1) entre la serie demandee et l'un des titres
    candidats (titre principal + titres alternatifs, toutes langues). On utilise
    une similarite SYMETRIQUE (Jaccard sur les tokens, complete d'un ratio de
    sequence) : un spin-off comme "Solo Leveling: Ragnarok" ne doit pas scorer
    aussi haut que "Solo Leveling" pour la requete "Solo Leveling" - la simple
    couverture des tokens demandes ne suffit pas (le spin-off les contient tous
    aussi). Le matching via un titre alternatif traduit reste possible (ex.
    "Solo Leveling" en titre alternatif d'une oeuvre au titre coreen romanise)."""
    want = _norm_tokens(series_name)
    if not want:
        return 0.0
    best = 0.0
    for title in titles:
        got = _norm_tokens(title)
        if not got:
            continue
        jaccard = len(want & got) / len(want | got)
        ratio = difflib.SequenceMatcher(
            None, " ".join(sorted(want)), " ".join(sorted(got))).ratio()
        best = max(best, jaccard, ratio)
    return best


# nom public : reutilise par anilist.py pour mesurer la ressemblance des titres
title_score = _title_score


def _title_matches(series_name: str, titles) -> bool:
    return _title_score(series_name, titles) >= _MIN_SCORE


def _all_titles(attr) -> list:
    """Tous les titres d'une entree : titre principal (toutes langues) + titres
    alternatifs, aplatis en une liste de chaines pour le matching."""
    titles = list((attr.get("title") or {}).values())
    for alt in attr.get("altTitles") or []:
        titles.extend(alt.values())
    return [t for t in titles if t]


# langues des titres alternatifs gardes pour la recherche dans la bibliotheque
# (francais, anglais, titres originaux et leurs romanisations) : MangaDex en
# liste souvent des dizaines (thai, arabe, russe...) qui ne serviraient qu'a
# gonfler l'index de recherche
_SEARCH_TITLE_LANGS = {"fr", "en", "ja", "ja-ro", "ko", "ko-ro", "zh", "zh-hk", "zh-ro"}


def _search_titles(attr) -> list:
    """Titres a indexer pour la recherche (voir core/search.known_titles) :
    titre principal et titres alternatifs dans les langues retenues."""
    titles = list((attr.get("title") or {}).values())
    for alt in attr.get("altTitles") or []:
        titles.extend(t for lang, t in alt.items() if lang in _SEARCH_TITLE_LANGS)
    return [t for t in dict.fromkeys(titles) if t]


def _display_title(attr, fallback: str) -> str:
    """Titre a afficher : anglais de preference, sinon le premier disponible."""
    t = attr.get("title") or {}
    return t.get("en") or next(iter(t.values()), None) or fallback


def _clean_author(name: str) -> str:
    """Retire le nom natif entre parentheses ("Oda Eiichirou (...)" ->
    "Oda Eiichirou", "DAUL (...)" -> "DAUL")."""
    return _PAREN_SUFFIX.sub("", name or "").strip()


def _main_author(relationships) -> list:
    """Auteur principal : premier "author" credite, sinon premier "artist".
    Renvoie une liste (0 ou 1 element) pour rester homogene avec les autres
    sources, qui ne gardent qu'un auteur principal."""
    authors, artists = [], []
    for rel in relationships or []:
        attr = rel.get("attributes") or {}
        name = _clean_author(attr.get("name"))
        if not name:
            continue
        if rel.get("type") == "author":
            authors.append(name)
        elif rel.get("type") == "artist":
            artists.append(name)
    picked = authors or artists
    return picked[:1]


def _people(relationships) -> list:
    return [_clean_author((rel.get("attributes") or {}).get("name"))
            for rel in relationships or [] if rel.get("type") in ("author", "artist")]


def _country_of(lang: str):
    if not lang:
        return None
    return _LANG_COUNTRY.get(lang.lower(), lang.upper()[:2])


def search_series(name: str, author_hint=None):
    """Cherche une serie par son nom. Renvoie {title, authors: [str],
    published_year, country, match_score, mangadex_id...} ou None si introuvable. Leve MangaDexError en cas
    de probleme reseau/HTTP/format."""
    params = [
        ("title", name),
        ("limit", "5"),
        ("includes[]", "author"),
        ("includes[]", "artist"),
        ("order[relevance]", "desc"),
    ]
    payload = _get_json(f"{BASE_URL}?{urllib.parse.urlencode(params)}")
    if payload is None:
        return None

    items = payload.get("data") or []
    if not items:
        return None

    # resultat dont un titre correspond le MIEUX a la serie demandee (et non le
    # premier passant un seuil) : MangaDex renvoie souvent un spin-off/une suite
    # en tete, qui couvre les memes tokens que l'oeuvre principale. On note
    # chaque candidat et on retient le meilleur au-dessus du seuil minimal.
    best, best_score, best_hinted = None, _MIN_SCORE, False
    for it in items:
        score = _title_score(name, _all_titles(it.get("attributes") or {}))
        if score < _MIN_SCORE:
            continue
        # homonymes : un auteur qui correspond a l'indice tire du nom de
        # fichier l'emporte sur un titre a peine plus ressemblant
        hinted = matches_author(author_hint, _people(it.get("relationships")))
        if (hinted, score) >= (best_hinted, best_score):
            best, best_score, best_hinted = it, score, hinted
    match = best
    if match is None:
        return None

    attr = match.get("attributes") or {}
    year = attr.get("year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None

    descriptions = attr.get("description") if isinstance(attr.get("description"), dict) else {}
    genres = [genre_fr(((t.get("attributes") or {}).get("name") or {}).get("en"))
              for t in (attr.get("tags") or [])
              if isinstance(t, dict) and (t.get("attributes") or {}).get("group") == "genre"]
    last_volume = str(attr.get("lastVolume") or "")
    return {
        "title": _display_title(attr, name),
        "titles": _search_titles(attr),
        "authors": _main_author(match.get("relationships")),
        "published_year": year,
        "country": _country_of(attr.get("originalLanguage")),
        # resume en francais quand MangaDex en a un, sinon en anglais
        "description": clean_description(descriptions.get("fr") or descriptions.get("en")),
        "genres": [g for g in genres if g],
        # dernier tome d'une serie terminee : nombre de tomes parus
        "volumes": int(last_volume) if last_volume.isdigit() else None,
        "match_score": round(best_score, 3),
        "mangadex_id": match.get("id"),
    }


def _get_json(url: str):
    """Requete GET -> JSON, ou None (404). Leve MangaDexError sinon."""
    _throttle()
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 429:
            _LIMITER.back_off(net.retry_after(e))
        raise MangaDexError(str(e)) from e
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        raise MangaDexError(str(e)) from e


def _number(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


# version du decoupage calcule par parse_aggregate : un cache d'une version
# anterieure est redemande (voir ChapterMapController)
RANGES_VERSION = 3


def _main_run(numbers):
    """Plus longue suite de chapitres consecutifs (ecart d'au plus un, les
    bonus « 12.5 » compris) : (premier, dernier). MangaDex range parfois un
    chapitre dans le mauvais tome (equipe de traduction qui se trompe) ; ces
    egares sont ecartes."""
    best = run = None
    for n in sorted(numbers):
        if run is not None and n - run[1] <= 1:
            run = (run[0], n, run[2] + 1)
        else:
            run = (n, n, 1)
        if best is None or run[2] > best[2]:
            best = run
    return best[0], best[1]


def parse_aggregate(payload) -> dict:
    """Decoupage officiel d'une oeuvre d'apres la reponse de /aggregate :
    {numero de tome (texte): [premier, dernier chapitre]}. Les chapitres
    hors tome (« none »), les numeros non numeriques et les chapitres
    egares dans un tome (voir _main_run) sont ignores ; un tome dont les
    chapitres ne suivent pas ceux du tome precedent est ecarte."""
    volumes = (payload or {}).get("volumes")
    if not isinstance(volumes, dict):
        return {}
    spans = []
    for key, vol in volumes.items():
        number = _number(key)
        chapters = vol.get("chapters") if isinstance(vol, dict) else None
        if number is None or not isinstance(chapters, dict):
            continue
        numbers = [n for n in (_number(c) for c in chapters) if n is not None]
        if numbers:
            spans.append((number, *_main_run(numbers)))
    ranges, last = {}, None
    for number, first, end in sorted(spans):
        if last is not None and first <= last:
            continue   # chevauche le tome precedent : decoupage douteux
        ranges[str(number)] = [first, end]
        last = end
    return ranges


# derniers chapitres parus : un numero isole, a plus de cet ecart du
# precedent, est un egare (ou une erreur de saisie) et n'est pas retenu
LATEST_MAX_GAP = 10


def parse_latest(payload, ranges=None):
    """(dernier tome paru, dernier chapitre paru) d'apres la reponse de
    /aggregate, ou None pour chacun s'il est inconnu. Le dernier tome est le
    plus grand du decoupage retenu (`ranges`, voir parse_aggregate) ; le
    dernier chapitre, le plus grand de la suite qui part du premier sans
    saut de plus de LATEST_MAX_GAP : prudent, il sous-estime plutot."""
    if ranges is None:
        ranges = parse_aggregate(payload)
    last_volume = max((int(float(k)) for k in ranges), default=None)
    volumes = (payload or {}).get("volumes")
    numbers = []
    for vol in volumes.values() if isinstance(volumes, dict) else ():
        chapters = vol.get("chapters") if isinstance(vol, dict) else None
        if isinstance(chapters, dict):
            numbers += [n for n in (_number(c) for c in chapters) if n is not None]
    last_chapter = None
    for n in sorted(numbers):
        if last_chapter is not None and n - last_chapter > LATEST_MAX_GAP:
            break
        last_chapter = n
    return last_volume, last_chapter


def aggregate(manga_id: str) -> dict:
    """Decoupage officiel et dernieres parutions de l'oeuvre MangaDex
    `manga_id`, toutes langues confondues : {"ranges": {tome: [premier,
    dernier chapitre]}, "last_volume", "last_chapter"}. Leve MangaDexError."""
    url = f"{BASE_URL}/{urllib.parse.quote(manga_id, safe='')}/aggregate"
    payload = _get_json(url)
    ranges = parse_aggregate(payload)
    last_volume, last_chapter = parse_latest(payload, ranges)
    return {"ranges": ranges, "last_volume": last_volume, "last_chapter": last_chapter}


def chapter_ranges(manga_id: str) -> dict:
    """Chapitres de chaque tome paru (voir aggregate)."""
    return aggregate(manga_id)["ranges"]


def series_aggregate(name: str, author_hint=None):
    """(identifiant MangaDex, aggregate(...)) de la serie `name`, ou None si
    MangaDex ne la connait pas. Leve MangaDexError."""
    found = search_series(name, author_hint)
    if not found or not found.get("mangadex_id"):
        return None
    return found["mangadex_id"], aggregate(found["mangadex_id"])


# ---------------------------------------------------------------- couvertures

COVERS_URL = "https://api.mangadex.org/cover"
UPLOADS_URL = "https://uploads.mangadex.org/covers"
# langue de couverture preferee : francaise, sinon anglaise, sinon celle de
# l'edition originale (le dessin est le meme, seuls logo et textes changent)
COVER_LOCALES = ("fr", "en", "ja")
COVER_MAX_BYTES = 8 * 1024 * 1024


def pick_cover(payload, volume) -> str:
    """Nom de fichier de la couverture du tome `volume` dans la reponse de
    /cover, dans la langue preferee (COVER_LOCALES), ou ""."""
    wanted = str(volume)
    found = {}
    for item in (payload or {}).get("data") or []:
        attr = (item or {}).get("attributes") or {}
        if str(attr.get("volume")) == wanted and attr.get("fileName"):
            found.setdefault(attr.get("locale"), attr["fileName"])
    for locale in COVER_LOCALES:
        if locale in found:
            return found[locale]
    return next(iter(found.values()), "")


def volume_cover(manga_id: str, volume) -> bytes:
    """Image (JPEG, 512 px de large) de la couverture officielle du tome
    `volume` de l'oeuvre `manga_id`, ou b"" si MangaDex n'en a pas. Leve
    MangaDexError."""
    # l'API ne filtre pas par tome : toutes les couvertures de l'oeuvre
    params = [("manga[]", manga_id), ("limit", "100")]
    name = pick_cover(_get_json(f"{COVERS_URL}?{urllib.parse.urlencode(params)}"), volume)
    if not name:
        return b""
    url = (f"{UPLOADS_URL}/{urllib.parse.quote(manga_id, safe='')}/"
           f"{urllib.parse.quote(name, safe='')}.512.jpg")
    _throttle()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read(COVER_MAX_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        raise MangaDexError(str(e)) from e
    if len(data) > COVER_MAX_BYTES:
        raise MangaDexError(f"couverture trop volumineuse : {url}")
    return data

