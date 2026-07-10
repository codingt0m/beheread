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
  alimenter la detection automatique du sens de lecture (voir reader.py).
"""

import difflib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://api.mangadex.org/manga"
TIMEOUT = 10
MIN_INTERVAL = 0.3
# MangaDex bloque les UA de navigateur : un identifiant applicatif est attendu.
USER_AGENT = "Beheread/1.0 (manga reader; +https://github.com/beheread)"

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

_last_request = 0.0


class MangaDexError(Exception):
    """Erreur reseau/HTTP/format - a distinguer d'une recherche sans resultat."""


def _throttle():
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request = time.monotonic()


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


def _title_matches(series_name: str, titles) -> bool:
    return _title_score(series_name, titles) >= _MIN_SCORE


def _all_titles(attr) -> list:
    """Tous les titres d'une entree : titre principal (toutes langues) + titres
    alternatifs, aplatis en une liste de chaines pour le matching."""
    titles = list((attr.get("title") or {}).values())
    for alt in attr.get("altTitles") or []:
        titles.extend(alt.values())
    return [t for t in titles if t]


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


def _country_of(lang: str):
    if not lang:
        return None
    return _LANG_COUNTRY.get(lang.lower(), lang.upper()[:2])


def search_series(name: str):
    """Cherche une serie par son nom. Renvoie {title, authors: [str],
    published_year, country} ou None si introuvable. Leve MangaDexError en cas
    de probleme reseau/HTTP/format."""
    params = [
        ("title", name),
        ("limit", "5"),
        ("includes[]", "author"),
        ("includes[]", "artist"),
        ("order[relevance]", "desc"),
    ]
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"

    _throttle()
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise MangaDexError(str(e)) from e
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        raise MangaDexError(str(e)) from e

    items = payload.get("data") or []
    if not items:
        return None

    # resultat dont un titre correspond le MIEUX a la serie demandee (et non le
    # premier passant un seuil) : MangaDex renvoie souvent un spin-off/une suite
    # en tete, qui couvre les memes tokens que l'oeuvre principale. On note
    # chaque candidat et on retient le meilleur au-dessus du seuil minimal.
    best, best_score = None, _MIN_SCORE
    for it in items:
        score = _title_score(name, _all_titles(it.get("attributes") or {}))
        if score >= best_score:
            best, best_score = it, score
    match = best
    if match is None:
        return None

    attr = match.get("attributes") or {}
    year = attr.get("year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None

    return {
        "title": _display_title(attr, name),
        "authors": _main_author(match.get("relationships")),
        "published_year": year,
        "country": _country_of(attr.get("originalLanguage")),
    }
