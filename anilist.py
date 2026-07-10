"""Client minimal pour l'API AniList (GraphQL, gratuite, sans authentification).

Utilisee en dernier recours pour retrouver les metadonnees d'une SERIE
entiere (pas par tome) : contrairement a MyAnimeList/Jikan, AniList gere
bien les synonymes et titres traduits (francais compris), ce qui la rend
plus efficace quand le nom de fichier est un titre localise.

Note technique : l'API est protegee par Cloudflare et bloque les requetes
dont l'en-tete User-Agent ressemble a un script (d'ou l'usage d'un User-Agent
de navigateur ci-dessous). Elle renvoie un code HTTP 404 (avec un corps JSON)
quand la recherche n'aboutit a rien - ce n'est pas une erreur reseau.
"""

import json
import time
import urllib.error
import urllib.request

URL = "https://graphql.anilist.co"
TIMEOUT = 8
MIN_INTERVAL = 0.7
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

_QUERY = """
query ($search: String) {
  Media(search: $search, type: MANGA) {
    title { romaji english native }
    staff(perPage: 1) { nodes { name { full } } }
    startDate { year }
    countryOfOrigin
  }
}
"""

_last_request = 0.0


class AniListError(Exception):
    """Erreur reseau/HTTP/format - a distinguer d'une recherche sans resultat."""


def _throttle():
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request = time.monotonic()


def search_series(name: str):
    """Cherche une serie par son nom. Renvoie {title, authors: [str],
    published_year} ou None si introuvable. Leve AniListError en cas de
    probleme reseau/HTTP/format (hors 404, qui signifie "non trouve")."""
    body = json.dumps({"query": _QUERY, "variables": {"search": name}}).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                "User-Agent": USER_AGENT})

    _throttle()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise AniListError(str(e)) from e
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        raise AniListError(str(e)) from e

    media = (payload.get("data") or {}).get("Media")
    if not media:
        return None

    titles = media.get("title") or {}
    title = titles.get("english") or titles.get("romaji") or titles.get("native") or name
    # seul l'auteur principal (premier membre du staff, generalement le
    # mangaka credite en premier) est garde
    staff_nodes = (media.get("staff") or {}).get("nodes", [])
    authors = [staff_nodes[0]["name"]["full"]] if staff_nodes and staff_nodes[0].get("name", {}).get("full") else []
    year = (media.get("startDate") or {}).get("year")
    # pays d'origine (ex. "JP", "KR", "CN") : indice pour deduire le sens de
    # lecture par defaut d'une serie quand l'archive n'a pas de ComicInfo.xml
    # (les mangas japonais se lisent droite -> gauche, le reste gauche -> droite)
    country = media.get("countryOfOrigin")

    return {"title": title, "authors": authors, "published_year": year,
            "country": country}
