"""Client minimal pour l'API Google Books (recherche publique, sans cle),
utilisee comme 2e priorite pour retrouver la date de sortie d'un TOME precis
- contrairement a AniList/MyAnimeList qui ne documentent que la serie dans
son ensemble. La couverture n'est pas recuperee ici : la premiere page de
l'archive suffit et evite toute dependance reseau pour l'affichage.

Aucune authentification requise pour une recherche simple, mais le quota
anonyme (sans cle API) est relativement bas et partage par adresse IP : des
erreurs 429 (trop de requetes) sont possibles, en particulier sur des reseaux
partages. Elles sont traitees comme un echec reseau ordinaire (voir
GoogleBooksError) et n'empechent pas le repli sur AniList.
"""

import difflib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://www.googleapis.com/books/v1/volumes"
TIMEOUT = 8
MIN_INTERVAL = 1.0
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

_last_request = 0.0


class GoogleBooksError(Exception):
    """Erreur reseau/HTTP/format - a distinguer d'une recherche sans resultat."""


def _throttle():
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request = time.monotonic()


def _norm_tokens(text: str):
    """Jeu de tokens alphanumeriques en minuscules d'un titre/nom de serie."""
    return set(re.findall(r"\w+", (text or "").casefold()))


def _title_matches(series_name: str, title: str) -> bool:
    """La recherche Google Books renvoie souvent un ouvrage sans rapport quand
    la serie n'est pas indexee (elle retourne le premier resultat, quel qu'il
    soit) : on ne retient un item que si son titre correspond vraiment a la
    serie demandee. Cela evite d'afficher un auteur/une date faux.

    Match si les tokens du nom de serie sont (presque) tous presents dans le
    titre du livre, ou si la ressemblance globale est suffisante."""
    want = _norm_tokens(series_name)
    got = _norm_tokens(title)
    if not want or not got:
        return False
    covered = len(want & got) / len(want)
    if covered >= 0.75:
        return True
    ratio = difflib.SequenceMatcher(
        None, " ".join(sorted(want)), " ".join(sorted(got))).ratio()
    return ratio >= 0.6


def search_volume(series_name: str, number=None, lang: str = "fr"):
    """Cherche un tome precis (nom de serie + numero). Renvoie
    {title, authors: [str], published_date, published_year} ou None si
    aucun resultat. Leve GoogleBooksError en cas de probleme reseau/HTTP/format."""
    query = f"{series_name} tome {number}" if number else series_name
    params = {"q": query, "maxResults": 5}
    if lang:
        params["langRestrict"] = lang
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"

    _throttle()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        raise GoogleBooksError(str(e)) from e

    items = payload.get("items") or []
    if not items:
        return None

    # On retient le premier item dont le titre correspond reellement a la serie
    # demandee (voir _title_matches) plutot que le premier resultat brut, qui
    # peut etre un ouvrage sans rapport quand la serie n'est pas indexee.
    info = None
    for item in items:
        vi = item.get("volumeInfo", {})
        if _title_matches(series_name, vi.get("title", "")):
            info = vi
            break
    if info is None:
        return None

    published = info.get("publishedDate")
    year = None
    if published:
        try:
            year = int(str(published)[:4])
        except (ValueError, TypeError):
            year = None

    authors = info.get("authors") or []

    return {
        "title": info.get("title"),
        "authors": authors[:1],   # seul l'auteur principal (premier de la liste) est garde
        "published_date": published,
        "published_year": year,
    }
