"""Orchestre la recuperation des metadonnees (auteur, date de sortie) d'un
tome, selon la strategie a cinq niveaux :

1. ComicInfo.xml (local, dans l'archive) - priorite absolue : fiable et
   100% hors ligne si l'utilisateur a tague ses fichiers.
2. Google Books - recherche combinant le titre de la serie et le numero du
   tome, pour obtenir la date de sortie de l'edition physique precise
   (pas de couverture : la premiere page de l'archive suffit pour ca).
3. AniList - recherche au niveau de la serie (pas de notion de tome), utile
   pour sa gestion des synonymes / titres traduits.
4. MangaDex - catalogue manga bien plus large (oeuvres de niche, series
   independantes/francaises, webtoons...).
5. BnF - dernier recours, pour tout ce qui n'est pas un manga : bande
   dessinee franco-belge, comics. Sa notice donne aussi le format physique
   du livre, indice du sens de lecture (voir ui/reader/display.py).

AniList renvoie toujours un resultat, meme pour une oeuvre qu'il ne connait
pas : il n'est retenu que si son titre ressemble vraiment au nom cherche
(meme seuil que le suivi AniList), sinon on passe a la source suivante.

Chaque couche n'est interrogee que si la precedente n'a rien donne
d'exploitable (ni auteur, ni annee). Aucune requete reseau n'est faite si
ComicInfo.xml suffit deja. Les deux niveaux "serie" (AniList puis MangaDex)
(AniList, MangaDex puis BnF) sont mutualises dans _search_series_sources :
leur resultat sert a la fois de
metadonnees du tome et d'entree de cache serie (partagee entre tous les tomes).
"""

import logging
import unicodedata

from beheread.core.anilist_track import AUTO_MATCH_MIN_SCORE
from beheread.infra import anilist, bnf, googlebooks, mangadex
from beheread.infra.archive import Archive

# Incrementee a chaque changement de la cascade (ajout d'une source, regle de
# selection). Un cache ecrit par une version anterieure est retente (voir
# is_stale), sans jamais retenter indefiniment un cache a jour :
# 2 : ajout de MangaDex ;
# 3 : ajout de la BnF, seuil de ressemblance AniList, pays d'origine ;
# 4 : une correspondance MangaDex approchante cede devant un titre exact a la BnF ;
# 5 : un resultat obtenu sans AniList (injoignable) est provisoire ;
# 6 : l'auteur glisse dans le nom de fichier departage les homonymes.
CASCADE_VERSION = 6

# sources dont un resultat ancien est a rafraichir (les resultats AniList
# d'avant la version 4 ont pu etre acceptes sans ressembler au titre cherche,
# et n'ont pas toujours leur pays d'origine). None : cache serie ecrit avant
# que la source n'y soit notee, donc forcement par AniList ou MangaDex.
# ComicInfo.xml, les saisies manuelles et Google Books (par tome, quota tres
# bas) ne sont pas concernes.
_REFRESHED_SOURCES = ("anilist", "mangadex", "series", None)

# en dessous, une correspondance MangaDex n'est qu'approchante (titre
# alternatif voisin : « Dead Girl Walking » pour « Walking Dead ») : la BnF
# est alors consultee aussi, et la correspondance la plus exacte l'emporte
_EXACT_SCORE = 0.95


def not_found_sentinel():
    return {"not_found": True, "cascade_version": CASCADE_VERSION}


def is_stale(cached) -> bool:
    """Vrai si ce cache est a retenter : resultat provisoire (obtenu alors
    qu'AniList etait injoignable), ou ecrit par une cascade plus ancienne -
    un "not_found" (une source ajoutee depuis peut aboutir) ou un resultat
    AniList/MangaDex (regles de selection changees). Un resultat perime reste
    affiche en attendant."""
    if cached and cached.get("partial"):
        return True
    if not cached or cached.get("cascade_version", 1) >= CASCADE_VERSION:
        return False
    return bool(cached.get("not_found")) or cached.get("source") in _REFRESHED_SOURCES



def _fold_accents(text: str) -> str:
    """Retire les accents/diacritiques (ex. "lumiere" au lieu de "lumiere"
    accentue). Constate empiriquement : la recherche AniList (et
    vraisemblablement Google Books) echoue souvent sur un titre francais
    accentue alors qu'elle aboutit sur sa version sans accents - les
    interroger avec la version repliee ameliore nettement le taux de succes."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _read_comicinfo_meta(path: str):
    if path.lower().endswith(".pdf"):
        return None   # pas de ComicInfo.xml dans un PDF : inutile de l'ouvrir
    try:
        ar = Archive(path)
    except Exception:
        logging.warning("Archive illisible pour la recherche ComicInfo.xml: %s",
                        path, exc_info=True)
        return None
    try:
        raw = ar.read_comicinfo()
    finally:
        ar.close()
    if not raw:
        return None
    return {
        "authors": raw.get("authors") or [],
        "published_year": raw.get("year"),
        "title": raw.get("title") or raw.get("series"),
    }


# noms de serie qui n'en sont pas : un fichier nomme seulement « Volume 1 »
# ou « Tome 3 » n'a rien a chercher (sinon AniList trouve « Full Volume »)
_GENERIC_NAMES = {"", "volume", "vol", "tome", "tomo", "chapitre", "chapter", "chap",
                  "episode", "cycle", "integrale", "book", "livre", "manga", "bd", "scan"}


def _searchable(series_name: str) -> bool:
    words = "".join(c if c.isalnum() else " " for c in _fold_accents(series_name or ""))
    return " ".join(words.casefold().split()) not in _GENERIC_NAMES


def _useful(data):
    return bool(data) and bool(data.get("authors") or data.get("published_year"))


def _search_series_sources(query_name: str, author_hint=None):
    """Recherche au niveau de la SERIE, en ligne, par ordre de priorite :
    AniList (donnees structurees, bons synonymes / titres traduits, retenu
    seulement si son titre ressemble au nom cherche), MangaDex (catalogue
    manga de niche), puis la BnF (BD, comics : tout ce qui n'est pas manga).
    Renvoie (series_data, network_ok) : series_data porte deja sa cle "source"
    et sert tel quel de metadonnees de tome comme d'entree de cache serie ;
    network_ok=False si une source a echoue reseau (a retenter, ne pas cacher
    un "rien trouve")."""
    network_ok = True
    try:
        al = anilist.search_series(query_name, author_hint=author_hint)
    except anilist.AniListError as e:
        logging.warning("AniList injoignable pour %r : %s", query_name, e)
        al, network_ok = None, False
    # sans reponse d'AniList, une source suivante peut trouver un homonyme
    # (« Vagabond » colorise a Hong Kong, « Monster » chinois) : son resultat
    # n'est alors que provisoire, reverifie a la session suivante
    partial = al is None and not network_ok
    if _useful(al) and (al.get("match_score") or 0) >= AUTO_MATCH_MIN_SCORE:
        return _stamped(al, "anilist"), network_ok

    try:
        md = mangadex.search_series(query_name, author_hint=author_hint)
    except mangadex.MangaDexError:
        md, network_ok = None, False
    md_score = (md.get("match_score") or 1.0) if _useful(md) else None
    if md_score is not None and md_score >= _EXACT_SCORE:
        return _stamped(md, "mangadex", partial), network_ok

    try:
        bf = bnf.search_series(query_name)
    except bnf.BnfError:
        bf, network_ok = None, False
    if _useful(bf) and (md_score is None or (bf.get("match_score") or 0) > md_score):
        return _stamped(bf, "bnf", partial), network_ok
    if md_score is not None:
        return _stamped(md, "mangadex", partial), network_ok

    return None, network_ok


def _stamped(data, source, partial=False):
    out = dict(data)
    out["source"] = source
    out["cascade_version"] = CASCADE_VERSION
    if partial:
        out["partial"] = True
    return out


def fetch_series(series_name: str, author_hint=None):
    """Recherche au niveau de la SERIE uniquement (auteur + annee de debut),
    AniList puis MangaDex. Une seule requete renseigne d'un coup tous les tomes
    de la serie - bien plus rapide, au premier scan d'une grosse bibliotheque,
    que d'attendre une recherche Google Books par tome (throttlee). Renvoie
    (series_data, ok) : series_data est le dict trouve (ou {"not_found": True}),
    ok=False si le reseau a echoue sans rien trouver (a retenter, ne pas
    cacher)."""
    if not _searchable(series_name):
        return not_found_sentinel(), True
    series, ok = _search_series_sources(_fold_accents(series_name), author_hint)
    if _useful(series):
        return series, True
    if not ok:
        return None, False
    return not_found_sentinel(), True


def fetch(path: str, series_name: str, volume, cached_series=None, online=True,
          author_hint=None):
    """Renvoie (volume_data, network_ok, series_data).

    online=False (recherche en ligne non autorisee par l'utilisateur) : seul
    ComicInfo.xml, local, est consulte ; a defaut, (None, False, None) - un
    « non trouve » n'est alors PAS a mettre en cache, pour que les sources en
    ligne soient interrogees si l'utilisateur les autorise plus tard.

    volume_data  : dict de metadonnees pour ce fichier precis, ou None.
    network_ok   : False si une couche reseau a echoue ET qu'aucune donnee
                   exploitable n'a ete trouvee (l'appelant ne doit alors pas
                   mettre en cache une absence de resultat - a retenter plus
                   tard).
    series_data  : dict AniList fraichement obtenu pour la SERIE (a mettre
                   en cache separement, partage entre tous les tomes), ou
                   None si non interroge ou deja fourni via cached_series.
    """
    info = _read_comicinfo_meta(path)
    if _useful(info):
        info["source"] = "comicinfo"
        return info, True, None
    if not online:
        return None, False, None
    if not _searchable(series_name):
        return None, True, not_found_sentinel()

    query_name = _fold_accents(series_name)
    network_ok = True

    try:
        gb = googlebooks.search_volume(query_name, volume)
    except googlebooks.GoogleBooksError:
        gb = None
        network_ok = False
    if _useful(gb):
        gb["source"] = "googlebooks"
        return gb, True, None

    # niveau serie (AniList puis MangaDex) : on reutilise le cache serie s'il
    # est deja renseigne (par le worker serie) et toujours a jour, sinon on
    # interroge le reseau (un cache "not_found" perime, ecrit par une cascade
    # plus courte, est traite comme absent : cf. is_stale).
    if cached_series is not None and not is_stale(cached_series):
        cached = None if cached_series.get("not_found") else cached_series
        if _useful(cached):
            out = dict(cached)
            out.setdefault("source", "series")
            out.setdefault("cascade_version", CASCADE_VERSION)
            return out, True, None
        return None, network_ok, None

    series, ok = _search_series_sources(query_name, author_hint)
    if not ok:
        network_ok = False
    if _useful(series):
        return dict(series), True, series
    series_data = not_found_sentinel() if ok else None
    return None, network_ok, series_data
