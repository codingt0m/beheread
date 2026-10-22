"""Orchestre la recuperation des metadonnees (auteur, date de sortie, nature,
nombre de tomes...) d'un tome, par ordre de priorite :

1. Metadonnees locales - priorite absolue : fiables et 100% hors ligne si
   l'utilisateur a tague ses fichiers. ComicInfo.xml (ou l'OPF d'un EPUB)
   dans l'archive, complete par le series.json de Mylar du dossier (comme
   Komga) : auteur, date, mais aussi genres, resume, nombre de tomes, ISBN.
2. ISBN du tome - celui de ComicInfo.xml (GTIN), sinon le code-barres de la
   quatrieme de couverture quand le scan l'inclut (voir core/barcode.py) :
   la notice BnF (a defaut Google Books) de ce tome precis.
3. Recherche au niveau de la SERIE (voir _search_series_sources) : la BnF
   d'abord, qui dit de quelle langue l'oeuvre est traduite et donc ce
   qu'elle est (BD, comics, manga, manhwa) ; les bases manga (AniList,
   MangaDex) seulement pour ce qui en releve ; Wikidata pour departager
   quand la BnF ne connait pas la serie. La BnF date aussi chaque tome.
4. Google Books - date de sortie du tome, quand la serie ne la donne pas
   (oeuvre trouvee dans une base manga, qui ne connait que la serie).
5. Les donnees de la serie seules.

Chaque couche n'est interrogee que si la precedente n'a rien donne
d'exploitable (ni auteur, ni annee). Aucune requete reseau n'est faite si les
metadonnees locales suffisent deja. La recherche de serie est mutualisee
(une seule par serie et par session, voir _search_series_once) : son
resultat sert a la fois de metadonnees du tome et d'entree de cache serie
(partagee entre tous les tomes).
"""

import json
import logging
import os
import threading

from beheread.core.series import matches_author
from beheread.core.text import GENERIC_NAMES, strip_accents
from beheread.infra import anilist, bnf, googlebooks, mangadex, wikidata
from beheread.infra.archive import Archive
from beheread.infra.mangadex import title_score

# Incrementee a chaque changement de la cascade (ajout d'une source, regle de
# selection). Un cache ecrit par une version anterieure est retente (voir
# is_stale), sans jamais retenter indefiniment un cache a jour :
# 2 : ajout de MangaDex ;
# 3 : ajout de la BnF, seuil de ressemblance AniList, pays d'origine ;
# 4 : une correspondance MangaDex approchante cede devant un titre exact a la BnF ;
# 5 : un resultat obtenu sans AniList (injoignable) est provisoire ;
# 6 : l'auteur glisse dans le nom de fichier departage les homonymes ;
# 7 : genres, resume et nombre de tomes parus (AniList, MangaDex) ;
# 8 : auteur AniList choisi par son role (plus un assistant cite en premier) ;
# 9 : la BnF (notices UNIMARC) d'abord, qui decide de la nature de l'oeuvre ;
#     Wikidata ; oeuvres pour adultes ecartees d'AniList ; ISBN du tome ;
# 10 : labels manga d'editeurs generalistes (« Combo » de Dargaud), collections
#      accentuees (« Shônen »).
CASCADE_VERSION = 10

# sources dont un resultat ancien est a rafraichir (regles de selection
# changees depuis). None : cache serie ecrit avant que la source n'y soit
# notee, donc forcement par AniList ou MangaDex. Les metadonnees locales,
# les saisies manuelles, l'ISBN et Google Books (par tome, quota tres bas)
# ne sont pas concernes.
_REFRESHED_SOURCES = ("anilist", "mangadex", "bnf", "wikidata", "series", None)

# sources locales (voir _read_comicinfo_meta)
LOCAL_SOURCES = ("comicinfo", "epub", "seriesjson")

# a partir de ce score, une correspondance est exacte (a la ponctuation et
# aux accents pres) ; en dessous, MangaDex n'est qu'approchant (titre
# alternatif voisin : « Dead Girl Walking » pour « Walking Dead »)
_EXACT_SCORE = 0.95
# ressemblance minimale d'un resultat AniList (titre ou synonyme) pour en
# faire les metadonnees d'une serie - plus exigeant que le suivi de lecture :
# AniList renvoie toujours une oeuvre, souvent un homonyme lointain
# (« Sunshine » pour « Sandman »)
_ANILIST_MIN_SCORE = 0.8
# ressemblance minimale entre le nom de la serie et celui du tome identifie
# par son ISBN (sinon : un autre livre, ou un fichier mal nomme)
_ISBN_MIN_SCORE = 0.5

MAX_SERIES_JSON_BYTES = 1024 * 1024


def not_found_sentinel():
    return {"not_found": True, "cascade_version": CASCADE_VERSION}


def is_stale(cached) -> bool:
    """Vrai si ce cache est a retenter : resultat provisoire (obtenu alors
    qu'une source etait injoignable), ou ecrit par une cascade plus ancienne -
    un "not_found" (une source ajoutee depuis peut aboutir) ou un resultat
    d'une source en ligne au niveau serie (regles de selection changees). Un
    resultat perime reste affiche en attendant."""
    if cached and cached.get("partial"):
        return True
    if not cached or cached.get("cascade_version", 1) >= CASCADE_VERSION:
        return False
    return bool(cached.get("not_found")) or cached.get("source") in _REFRESHED_SOURCES


def fold_accents(text: str) -> str:
    """Nom a envoyer aux sources en ligne, sans accents ni diacritiques.
    Constate empiriquement : la recherche AniList (et vraisemblablement
    Google Books) echoue souvent sur un titre francais accentue alors
    qu'elle aboutit sur sa version sans accents - les interroger avec la
    version repliee ameliore nettement le taux de succes."""
    return strip_accents(text)


def _read_series_json(folder):
    """Metadonnees du series.json de Mylar dans `folder` (format repris par
    Komga et Kavita), ou None : {title, published_year, publisher,
    description, volumes}."""
    path = os.path.join(folder, "series.json")
    try:
        if os.path.getsize(path) > MAX_SERIES_JSON_BYTES:
            return None
        with open(path, "rb") as f:
            meta = (json.loads(f.read().decode("utf-8")) or {}).get("metadata") or {}
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(meta, dict):
        return None

    def integer(key):
        try:
            value = int(meta.get(key))
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None
    description = meta.get("description_text") or meta.get("description_formatted")
    return {"title": meta.get("name") if isinstance(meta.get("name"), str) else None,
            "published_year": integer("year"),
            "publisher": meta.get("publisher") if isinstance(meta.get("publisher"), str) else None,
            "description": description if isinstance(description, str) else "",
            "volumes": integer("total_issues")}


def _read_comicinfo_meta(path: str):
    """Metadonnees locales du tome : ComicInfo.xml (ou OPF d'un EPUB),
    completees par le series.json du dossier. None si rien."""
    raw = None
    if not path.lower().endswith(".pdf"):   # pas de ComicInfo.xml dans un PDF
        try:
            ar = Archive(path)
        except Exception:
            logging.warning("Archive illisible pour la recherche ComicInfo.xml: %s",
                            path, exc_info=True)
            ar = None
        if ar is not None:
            try:
                raw = ar.read_comicinfo()
            finally:
                ar.close()
    sj = _read_series_json(os.path.dirname(path))
    if not raw and not sj:
        return None
    raw, sj = raw or {}, sj or {}
    out = {
        "authors": raw.get("authors") or [],
        "published_year": raw.get("year"),
        "title": raw.get("title") or raw.get("series") or sj.get("title"),
        "genres": raw.get("genres") or [],
        "description": raw.get("summary") or sj.get("description") or "",
        "volumes": raw.get("count") or sj.get("volumes"),
        "publisher": raw.get("publisher") or sj.get("publisher"),
        "isbn": raw.get("gtin") or "",
        "embedded": "epub" if raw.get("embedded") == "opf" else
                    ("comicinfo" if raw else "seriesjson"),
    }
    if not out["published_year"] and not out["authors"]:
        out["published_year"] = sj.get("published_year")   # debut de la serie
        if out["published_year"]:
            out["embedded"] = "seriesjson"
    return out


def _scan_isbn(path: str):
    """ISBN lu en code-barres dans le tome (voir Archive.find_isbn), ou None.
    Jamais pour un espace reserve cloud : lire ses pages le telechargerait."""
    from beheread.infra.storage import is_cloud_placeholder
    if is_cloud_placeholder(path):
        return None
    try:
        ar = Archive(path)
    except Exception:
        return None
    try:
        return ar.find_isbn()
    except Exception:
        logging.warning("Recherche du code-barres impossible : %s", path, exc_info=True)
        return None
    finally:
        ar.close()


def _searchable(series_name: str) -> bool:
    """Faux pour un nom qui n'en est pas un (« Volume », « Tome ») : il n'y
    a rien a chercher (sinon AniList trouve « Full Volume »)."""
    words = "".join(c if c.isalnum() else " " for c in fold_accents(series_name or ""))
    return " ".join(words.casefold().split()) not in GENERIC_NAMES


def _useful(data):
    return bool(data) and bool(data.get("authors") or data.get("published_year"))


def _with_local(data, local):
    """`data` complete par ce que les metadonnees locales sont seules a
    donner (genres, resume, nombre de tomes, editeur, ISBN)."""
    if not local:
        return data
    out = dict(data)
    for key in ("genres", "description", "volumes", "publisher", "isbn"):
        if local.get(key) and not out.get(key):
            out[key] = local[key]
    return out


def _local_result(local):
    out = {k: v for k, v in local.items() if k != "embedded" and v not in (None, "", [])}
    out.setdefault("authors", [])
    out["source"] = local.get("embedded", "comicinfo")
    return out


def _nature(bf):
    """Nature d'une oeuvre d'apres sa notice BnF : "western" (BD, comics :
    traduit d'une langue occidentale, ou album francais), "manga" (traduit
    du japonais), "manhwa" (du coreen ou du chinois), "manfra" (manga
    francais : collection ou editeur manga), "french" (oeuvre francaise sans
    indice), None (rien, ou notices contradictoires)."""
    if not _useful(bf):
        return None
    origin = bf.get("origin")
    if origin == "jpn":
        return "manga"
    if origin in bnf.ASIAN_WESTERN_READING:
        return "manhwa"
    if origin and origin != "fre":
        return "western"
    if origin == "fre":
        return {"bd": "western", "manga": "manfra"}.get(bf.get("format"), "french")
    return None


def _compatible(candidate, bf) -> bool:
    """Faux si la BnF et la base manga citent des auteurs differents : deux
    oeuvres homonymes (« Monster » d'Urasawa et un « MONSTER » coreen)."""
    if not bf:
        return True
    ours = bf.get("creators") or bf.get("authors")
    theirs = candidate.get("authors")
    return not ours or not theirs or matches_author(ours, theirs)


def _search_manga_sources(query_name, author_hint, bf, strict):
    """AniList puis MangaDex. Renvoie (resultat estampille ou None, reseau
    ok, AniList a repondu). `strict` : la BnF connait une oeuvre francaise
    (ou de nature indecise) de ce nom - une base manga n'est alors retenue
    que pour un titre exact."""
    network_ok, answered = True, True
    min_score = _EXACT_SCORE if strict else _ANILIST_MIN_SCORE
    # oeuvres pour adultes : seulement si la BnF en confirme les auteurs (un
    # seinen explicite comme « Welcome Back, Alice » ; jamais un hentai qui
    # n'aurait que le titre en commun)
    adult = bool(bf and (bf.get("creators") or bf.get("authors")))
    try:
        al = anilist.search_series(query_name, author_hint=author_hint, adult=adult)
    except anilist.AniListError as e:
        logging.warning("AniList injoignable pour %r : %s", query_name, e)
        al, network_ok, answered = None, False, False
    if _useful(al) and (al.get("match_score") or 0) >= min_score and _compatible(al, bf):
        return ("anilist", al), network_ok, answered

    try:
        md = mangadex.search_series(query_name, author_hint=author_hint)
    except mangadex.MangaDexError:
        md, network_ok = None, False
    if _useful(md) and _compatible(md, bf):
        md_score = md.get("match_score") or 1.0
        # approchant : retenu seulement si la BnF ne trouve pas mieux
        if md_score >= _EXACT_SCORE or (
                not strict and md_score > ((bf or {}).get("match_score") or 0)):
            return ("mangadex", md), network_ok, answered
    return None, network_ok, answered


def _wikidata(query_name, author_hint):
    """(resultat Wikidata ou None, reseau ok)."""
    try:
        return wikidata.search_series(query_name, author_hint=author_hint), True
    except wikidata.WikidataError as e:
        logging.info("Wikidata injoignable pour %r : %s", query_name, e)
        return None, False


def _vetoes(wd, manga, author_hint) -> bool:
    """Vrai si Wikidata ne connait sous ce nom exact qu'une BD ou un comics,
    pas de manga, et que rien ne rattache le manga trouve a cette oeuvre-la
    (meme auteur, ou auteur indique par le nom de fichier) : c'est un
    homonyme (« Invincible » de Kirkman et un manga japonais)."""
    if not wd or (wd.get("match_score") or 0) < _EXACT_SCORE:
        return False
    if set(wd.get("kinds") or ()) != {"comics"}:
        return False
    authors = manga.get("authors")
    if matches_author(author_hint, authors):
        return False
    return not (wd.get("authors") and matches_author(wd["authors"], authors))


def _search_series_sources(query_name: str, author_hint=None):
    """Recherche au niveau de la SERIE, en ligne. Renvoie (series_data,
    network_ok) : series_data porte deja sa cle "source" et sert tel quel de
    metadonnees de tome comme d'entree de cache serie ; network_ok=False si
    une source a echoue reseau (a retenter, ne pas cacher un "rien trouve").

    1. La BnF : traduite d'une langue occidentale, ou album francais, c'est
       une BD ou un comics - sa notice fait foi, les bases manga ne sont pas
       consultees (elles trouveraient un homonyme : « Saga », « Batman »).
    2. Sinon AniList puis MangaDex, retenus seulement si leurs auteurs
       concordent avec ceux de la BnF ; pour une oeuvre francaise sans indice
       de manga, il leur faut en plus un titre exact (Radiant oui ; Mortelle
       Adèle, inconnue d'eux, reste une BD).
    3. La BnF ne connait pas la serie : Wikidata verifie que le manga trouve
       n'est pas l'homonyme d'un comics, et sert de source a defaut.
    Sans reponse de la BnF ou d'AniList, un resultat n'est que provisoire,
    reverifie a la session suivante."""
    network_ok, partial = True, False
    try:
        bf = bnf.search_series(query_name, author_hint=author_hint)
    except bnf.BnfError as e:
        logging.info("BnF injoignable pour %r : %s", query_name, e)
        bf, network_ok, partial = None, False, True
    if not _useful(bf):
        bf = None
    nature = _nature(bf)
    if nature == "western":
        return _stamped(bf, "bnf"), network_ok

    strict = bf is not None and nature not in ("manga", "manhwa")
    manga, ok, answered = _search_manga_sources(query_name, author_hint, bf, strict)
    network_ok = network_ok and ok
    partial = partial or not answered
    if manga is not None:
        source, data = manga
        if bf is None:
            wd, wd_ok = _wikidata(query_name, author_hint)
            partial = partial or not wd_ok
            if _vetoes(wd, data, author_hint):
                return (_stamped(wd, "wikidata", partial) if _useful(wd) else None), network_ok
        return _stamped(data, source, partial), network_ok

    if bf is not None:
        out = dict(bf)
        if nature == "french" and out.get("format") is None and answered and ok:
            out["format"] = "bd"   # oeuvre francaise inconnue des bases manga
        return _stamped(out, "bnf", partial), network_ok

    wd, wd_ok = _wikidata(query_name, author_hint)
    network_ok = network_ok and wd_ok
    if _useful(wd) and (wd.get("match_score") or 0) >= _EXACT_SCORE:
        return _stamped(wd, "wikidata", partial), network_ok
    return None, network_ok


# recherches de serie deja faites pendant la session : (nom replie, indices
# d'auteur) -> [threading.Event, resultat]. Les tomes d'une serie partent
# tous avant la reponse de la premiere recherche (leur cache serie, capture au
# lancement, est vide) : sans ce partage, chaque tome refaisait la meme
# recherche BnF, AniList, MangaDex...
_series_lock = threading.Lock()
_series_memo = {}
SERIES_WAIT_TIMEOUT = 300   # secondes


def clear_series_memo():
    """Oublie les recherches de serie de la session (rechargement demande par
    l'utilisateur, metadonnees en ligne effacees)."""
    with _series_lock:
        _series_memo.clear()


def _search_series_once(query_name: str, author_hint=None):
    """_search_series_sources, partage pour la session : une recherche deja
    faite, ou en cours dans un autre thread, n'est pas refaite. Un echec
    reseau n'est pas memorise : la recherche suivante retente."""
    key = (query_name.casefold(), tuple(author_hint or ()))
    with _series_lock:
        slot = _series_memo.get(key)
        owner = slot is None
        if owner:
            slot = _series_memo[key] = [threading.Event(), None]
    if not owner:
        # borne de securite : une recherche dure au plus quelques requetes
        if not slot[0].wait(SERIES_WAIT_TIMEOUT):
            return None, False
        return slot[1] or (None, False)
    try:
        slot[1] = _search_series_sources(query_name, author_hint)
    finally:
        with _series_lock:
            if slot[1] is None or not slot[1][1]:
                _series_memo.pop(key, None)
        slot[0].set()
    return slot[1]


def _stamped(data, source, partial=False):
    out = dict(data)
    out["source"] = source
    out["cascade_version"] = CASCADE_VERSION
    if partial:
        out["partial"] = True
    return out


def fetch_series(series_name: str, author_hint=None):
    """Recherche au niveau de la SERIE uniquement (voir
    _search_series_sources). Une seule recherche renseigne d'un coup tous
    les tomes de la serie - bien plus rapide, au premier scan d'une grosse
    bibliotheque, que d'attendre une recherche par tome (throttlee). Renvoie
    (series_data, ok) : series_data est le dict trouve (ou {"not_found":
    True}), ok=False si le reseau a echoue sans rien trouver (a retenter, ne
    pas cacher)."""
    if not _searchable(series_name):
        return not_found_sentinel(), True
    series, ok = _search_series_once(fold_accents(series_name), author_hint)
    if _useful(series):
        return series, True
    if not ok:
        return None, False
    return not_found_sentinel(), True


def _isbn_meta(isbn, series_name, volume):
    """(metadonnees du tome identifie par son ISBN ou None, reseau ok). Le
    tome n'est retenu que s'il appartient bien a la serie (titre voisin ou
    meme numero) : un code-barres peut etre celui d'un autre livre (page de
    publicite)."""
    ok = True
    try:
        found = bnf.search_isbn(isbn)
    except bnf.BnfError:
        found, ok = None, False
    if not _useful(found):
        try:
            found = googlebooks.search_isbn(isbn)
        except googlebooks.GoogleBooksError:
            found, ok = None, False
        if _useful(found):
            found["series"] = found.get("title")
    if not _useful(found):
        return None, ok
    series = found.get("series") or found.get("title") or ""
    similar = title_score(fold_accents(series_name), [fold_accents(series)]) >= _ISBN_MIN_SCORE
    same_number = volume is not None and found.get("number") is not None \
        and float(found["number"]) == float(volume)
    if not (similar or same_number):
        logging.info("ISBN %s : %r ne semble pas etre un tome de %r", isbn, series, series_name)
        return None, ok
    out = {k: v for k, v in found.items()
           if k not in ("series", "number", "title", "origin") and v not in (None, "", [])}
    out.setdefault("authors", [])
    out["title"] = series or series_name
    out["titles"] = [t for t in dict.fromkeys((series, found.get("title"))) if t]
    out["isbn"] = found.get("isbn") or isbn
    out["source"] = "isbn"
    return out, ok


def _series_copy(series, year=None):
    """Metadonnees de serie reprises pour un tome (sans la table des dates
    de chaque tome), avec la date propre du tome si elle est connue."""
    out = {k: v for k, v in series.items() if k != "volume_years"}
    out.setdefault("source", "series")
    out.setdefault("cascade_version", CASCADE_VERSION)
    if year:
        out["published_year"] = year
    return out


def volume_year(series, volume):
    """Annee de sortie du tome `volume` d'apres la serie (BnF), ou None."""
    years = (series or {}).get("volume_years") or {}
    if volume is None or not years:
        return None
    try:
        number = float(volume)
    except (TypeError, ValueError):
        return None
    return years.get(str(int(number))) if number.is_integer() else None


def fetch(path: str, series_name: str, volume, cached_series=None, online=True,
          author_hint=None):
    """Renvoie (volume_data, network_ok, series_data).

    online=False (recherche en ligne non autorisee par l'utilisateur) : seules
    les metadonnees locales sont consultees ; a defaut, (None, False, None) -
    un « non trouve » n'est alors PAS a mettre en cache, pour que les sources
    en ligne soient interrogees si l'utilisateur les autorise plus tard.

    volume_data  : dict de metadonnees pour ce fichier precis, ou None.
    network_ok   : False si une couche reseau a echoue ET qu'aucune donnee
                   exploitable n'a ete trouvee (l'appelant ne doit alors pas
                   mettre en cache une absence de resultat - a retenter plus
                   tard).
    series_data  : dict fraichement obtenu pour la SERIE (a mettre en cache
                   separement, partage entre tous les tomes), ou None si non
                   interroge ou deja fourni via cached_series.
    """
    local = _read_comicinfo_meta(path)
    if _useful(local):
        return _local_result(local), True, None
    if not online:
        return None, False, None
    if not _searchable(series_name):
        return None, True, not_found_sentinel()

    query_name = fold_accents(series_name)
    network_ok = True

    isbn = (local or {}).get("isbn") or _scan_isbn(path)
    if isbn:
        tome, ok = _isbn_meta(isbn, series_name, volume)
        network_ok = network_ok and ok
        if _useful(tome):
            return _with_local(tome, local), True, None

    # niveau serie : le cache serie s'il est deja renseigne (par le worker
    # serie) et toujours a jour, sinon le reseau (un cache "not_found"
    # perime, ecrit par une cascade plus courte, est traite comme absent :
    # cf. is_stale)
    series_data = None
    if cached_series is not None and not is_stale(cached_series):
        series = None if cached_series.get("not_found") else cached_series
    else:
        series, ok = _search_series_once(query_name, author_hint)
        network_ok = network_ok and ok
        series_data = series if _useful(series) else (not_found_sentinel() if ok else None)
    if not _useful(series):
        series = None

    year = volume_year(series, volume)
    if series is not None and year:
        return _with_local(_series_copy(series, year), local), True, series_data

    try:
        gb = googlebooks.search_volume(query_name, volume)
    except googlebooks.GoogleBooksError:
        gb = None
        network_ok = False
    if _useful(gb):
        gb = {k: v for k, v in gb.items() if v not in (None, "", [])}
        gb["source"] = "googlebooks"
        return _with_local(gb, local), True, series_data

    if series is not None:
        return _with_local(_series_copy(series), local), True, series_data
    return None, network_ok, series_data
