"""Client minimal pour l'API AniList (GraphQL, gratuite).

Deux usages :

1. Metadonnees (sans authentification) : recherche d'une SERIE entiere (pas
   par tome). AniList gere bien les synonymes et titres traduits (francais
   compris), utile quand le nom de fichier est un titre localise.
2. Suivi de lecture (avec le jeton de l'utilisateur) : lecture et mise a jour
   de son entree de liste pour une oeuvre (voir anilist_tracker.py).

Authentification (« implicit grant ») : Beheread est enregistre une fois
comme application AniList par le developpeur (Client ID dans beheread/config.py) ;
l'utilisateur clique « Se connecter », autorise Beheread dans son navigateur,
et le jeton revient tout seul (anilist_auth.py). Il est chiffre localement
(secret_store.py) et n'apparait jamais dans le journal.

Note technique : l'API est protegee par Cloudflare et bloque les requetes
dont l'en-tete User-Agent ressemble a un script (d'ou l'usage d'un User-Agent
de navigateur ci-dessous). Elle renvoie un code HTTP 404 (avec un corps JSON)
quand la recherche n'aboutit a rien - ce n'est pas une erreur reseau.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from beheread.core import anilist_track
from beheread.infra.mangadex import title_score

URL = "https://graphql.anilist.co"
AUTHORIZE_URL = "https://anilist.co/api/v2/oauth/authorize"
TIMEOUT = 8
MIN_INTERVAL = 0.7
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

_SEARCH = """
query ($search: String) {
  Media(search: $search, type: MANGA) {
    id
    title { romaji english native }
    synonyms
    staff(perPage: 1) { nodes { name { full } } }
    startDate { year }
    countryOfOrigin
    volumes
    chapters
  }
}
"""

_VIEWER = "query { Viewer { id name } }"

_MEDIA_ENTRY = """
query ($id: Int) {
  Media(id: $id, type: MANGA) {
    id
    title { romaji english }
    volumes
    chapters
    siteUrl
    mediaListEntry { status progress progressVolumes }
  }
}
"""

_SAVE = """
mutation ($mediaId: Int, $status: MediaListStatus, $progress: Int, $progressVolumes: Int) {
  SaveMediaListEntry(mediaId: $mediaId, status: $status, progress: $progress,
                     progressVolumes: $progressVolumes) {
    status progress progressVolumes
  }
}
"""

_last_request = 0.0
_throttle_lock = threading.Lock()


class AniListError(Exception):
    """Erreur reseau/HTTP/format - a distinguer d'une recherche sans resultat."""


class AniListAuthError(AniListError):
    """Jeton refuse (invalide, expire ou revoque) : reconnexion necessaire."""


class AniListRefused(AniListError):
    """Ecriture refusee par Beheread lui-meme : elle aurait retire ou fait
    reculer quelque chose sur la liste de l'utilisateur."""


def _throttle():
    """Espace les requetes d'au moins MIN_INTERVAL. Sous verrou : plusieurs
    pools de threads (metadonnees par tome et par serie, suivi) interrogent
    la meme API en parallele, et sans verrou ils pouvaient partir en meme temps."""
    global _last_request
    with _throttle_lock:
        elapsed = time.monotonic() - _last_request
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)
        _last_request = time.monotonic()


def _post(query: str, variables: dict, token: str = None):
    """Execute une requete GraphQL. Renvoie le champ `data`, ou None pour un
    404 (recherche sans resultat)."""
    # verrou de principe : aucune requete de suppression ne peut partir,
    # quel que soit l'appelant (Beheread ne fait qu'ajouter sur AniList)
    if "delete" in query.lower():
        raise AniListRefused("requête de suppression interdite")
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(URL, data=body, method="POST", headers=headers)
    _throttle()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if token and e.code in (400, 401, 403):
            raise AniListAuthError(f"HTTP {e.code}") from e
        if e.code == 429:
            raise AniListError("limite de requêtes AniList atteinte, nouvel essai plus tard") from e
        raise AniListError(f"HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        raise AniListError(str(e)) from e
    if payload.get("errors") and not payload.get("data"):
        raise AniListError(str(payload["errors"][0].get("message", "erreur AniList")))
    return payload.get("data") or {}


# ---------------------------------------------------------------- metadonnees

def search_series(name: str):
    """Cherche une serie par son nom. Renvoie {title, authors: [str],
    published_year, country, anilist_id, volumes, match_score} ou None si
    introuvable. Leve AniListError en cas de probleme reseau/HTTP/format (hors
    404, qui signifie "non trouve").

    match_score (0..1) mesure la ressemblance entre le nom cherche et les
    titres de l'oeuvre trouvee (titres + synonymes) : la recherche AniList est
    tolerante et renvoie toujours « quelque chose ». Les metadonnees s'en
    contentent (comme avant) ; le suivi de lecture, qui ecrit sur le compte de
    l'utilisateur, exige un score suffisant."""
    data = _post(_SEARCH, {"search": name})
    media = (data or {}).get("Media")
    if not media:
        return None

    titles = media.get("title") or {}
    title = titles.get("english") or titles.get("romaji") or titles.get("native") or name
    all_titles = [t for t in titles.values() if t] + list(media.get("synonyms") or [])
    # seul l'auteur principal (premier membre du staff, generalement le
    # mangaka credite en premier) est garde
    staff_nodes = (media.get("staff") or {}).get("nodes", [])
    authors = ([staff_nodes[0]["name"]["full"]]
               if staff_nodes and staff_nodes[0].get("name", {}).get("full") else [])
    year = (media.get("startDate") or {}).get("year")
    # pays d'origine (ex. "JP", "KR", "CN") : indice pour deduire le sens de
    # lecture par defaut d'une serie quand l'archive n'a pas de ComicInfo.xml
    country = media.get("countryOfOrigin")

    return {"title": title, "authors": authors, "published_year": year,
            "country": country, "anilist_id": media.get("id"),
            "volumes": media.get("volumes"),
            "match_score": round(title_score(name, all_titles), 3)}


# ---------------------------------------------------------------- suivi (authentifie)

def authorize_url(client_id: str) -> str:
    """Page d'autorisation a ouvrir dans le navigateur. Apres accord, AniList
    renvoie vers l'adresse de redirection enregistree pour l'application
    (voir beheread/config.py), le jeton dans le fragment de l'adresse."""
    return f"{AUTHORIZE_URL}?" + urllib.parse.urlencode(
        {"client_id": client_id.strip(), "response_type": "token"})


def viewer(token: str) -> dict:
    """Compte associe au jeton : {id, name}. Leve AniListAuthError si refuse."""
    data = _post(_VIEWER, {}, token)
    v = (data or {}).get("Viewer")
    if not v:
        raise AniListAuthError("jeton refusé")
    return {"id": v.get("id"), "name": v.get("name")}


def media_entry(token: str, media_id: int):
    """{id, title, volumes, chapters, url, entry} ou None si l'oeuvre n'existe
    pas ; `entry` = {status, progress, progressVolumes} ou None si l'oeuvre
    n'est pas dans la liste de l'utilisateur."""
    data = _post(_MEDIA_ENTRY, {"id": int(media_id)}, token)
    media = (data or {}).get("Media")
    if not media:
        return None
    titles = media.get("title") or {}
    return {"id": media.get("id"),
            "title": titles.get("english") or titles.get("romaji") or str(media_id),
            "volumes": media.get("volumes"), "chapters": media.get("chapters"),
            "url": media.get("siteUrl"), "entry": media.get("mediaListEntry")}


def save_entry(token: str, media_id: int, changes: dict, current_entry) -> dict:
    """Enregistre les champs `changes` (status, progress, progressVolumes).
    `current_entry` : l'entree AniList lue juste avant (media_entry). Refuse
    (AniListRefused) toute ecriture qui ne serait pas purement additive."""
    if not anilist_track.is_additive(changes, current_entry):
        raise AniListRefused(f"mise à jour non additive refusée : {changes}")
    variables = {"mediaId": int(media_id)}
    variables.update({k: v for k, v in changes.items()
                      if k in ("status", "progress", "progressVolumes")})
    data = _post(_SAVE, variables, token)
    return (data or {}).get("SaveMediaListEntry") or {}


_MEDIA_URL = re.compile(r"anilist\.co/manga/(\d+)", re.IGNORECASE)


def parse_media_ref(text: str):
    """Identifiant AniList depuis une URL (« https://anilist.co/manga/30002/... »)
    ou un nombre saisi tel quel. None si rien d'exploitable."""
    text = (text or "").strip()
    m = _MEDIA_URL.search(text)
    if m:
        return int(m.group(1))
    return int(text) if text.isdigit() else None
