"""Orchestre la recuperation des metadonnees (auteur, date de sortie) d'un
tome, selon la strategie a quatre niveaux :

1. ComicInfo.xml (local, dans l'archive) - priorite absolue : fiable et
   100% hors ligne si l'utilisateur a tague ses fichiers.
2. Google Books - recherche combinant le titre de la serie et le numero du
   tome, pour obtenir la date de sortie de l'edition physique precise
   (pas de couverture : la premiere page de l'archive suffit pour ca).
3. AniList - recherche au niveau de la serie (pas de notion de tome), utile
   pour sa gestion des synonymes / titres traduits.
4. MangaDex - dernier recours, au catalogue bien plus large (oeuvres de niche,
   series independantes/francaises, webtoons...) : permet a un maximum de
   fichiers d'obtenir tout de meme auteur et annee quand les autres echouent.

Chaque couche n'est interrogee que si la precedente n'a rien donne
d'exploitable (ni auteur, ni annee). Aucune requete reseau n'est faite si
ComicInfo.xml suffit deja. Les deux niveaux "serie" (AniList puis MangaDex)
sont mutualises dans _search_series_sources : leur resultat sert a la fois de
metadonnees du tome et d'entree de cache serie (partagee entre tous les tomes).
"""

import logging
import unicodedata

import anilist
import googlebooks
import mangadex
from archive_handler import Archive

# Incrementee a chaque ajout/retrait d'une source dans la cascade (ex. l'ajout
# de MangaDex). Un cache "not_found" ecrit par une version anterieure peut
# desormais aboutir (une nouvelle source a ete ajoutee depuis) : voir
# is_stale_not_found, qui invalide ces entrees pour qu'elles soient retentees
# automatiquement, sans jamais retenter indefiniment un "not_found" a jour.
CASCADE_VERSION = 2


def not_found_sentinel():
    return {"not_found": True, "cascade_version": CASCADE_VERSION}


def is_stale_not_found(cached) -> bool:
    """Vrai si ce cache "not_found" date d'une cascade plus ancienne (moins de
    sources interrogees a l'epoque) : a traiter comme absent (retenter), pas
    comme un echec definitif."""
    return (bool(cached) and cached.get("not_found")
            and cached.get("cascade_version", 1) < CASCADE_VERSION)


def _fold_accents(text: str) -> str:
    """Retire les accents/diacritiques (ex. "lumiere" au lieu de "lumiere"
    accentue). Constate empiriquement : la recherche AniList (et
    vraisemblablement Google Books) echoue souvent sur un titre francais
    accentue alors qu'elle aboutit sur sa version sans accents - les
    interroger avec la version repliee ameliore nettement le taux de succes."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _read_comicinfo_meta(path: str):
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


def _useful(data):
    return bool(data) and bool(data.get("authors") or data.get("published_year"))


def _search_series_sources(query_name: str):
    """Recherche au niveau de la SERIE, en ligne, par ordre de priorite :
    AniList (donnees structurees, bons synonymes / titres traduits) puis
    MangaDex (catalogue de niche le plus large, la ou AniList est muet).
    Renvoie (series_data, network_ok) : series_data porte deja sa cle "source"
    et sert tel quel de metadonnees de tome comme d'entree de cache serie ;
    network_ok=False si une source a echoue reseau (a retenter, ne pas cacher
    un "rien trouve")."""
    network_ok = True
    try:
        al = anilist.search_series(query_name)
    except anilist.AniListError:
        al, network_ok = None, False
    if _useful(al):
        al = dict(al)
        al["source"] = "anilist"
        return al, network_ok

    try:
        md = mangadex.search_series(query_name)
    except mangadex.MangaDexError:
        md, network_ok = None, False
    if _useful(md):
        md = dict(md)
        md["source"] = "mangadex"
        return md, network_ok

    return None, network_ok


def fetch_series(series_name: str):
    """Recherche au niveau de la SERIE uniquement (auteur + annee de debut),
    AniList puis MangaDex. Une seule requete renseigne d'un coup tous les tomes
    de la serie - bien plus rapide, au premier scan d'une grosse bibliotheque,
    que d'attendre une recherche Google Books par tome (throttlee). Renvoie
    (series_data, ok) : series_data est le dict trouve (ou {"not_found": True}),
    ok=False si le reseau a echoue sans rien trouver (a retenter, ne pas
    cacher)."""
    series, ok = _search_series_sources(_fold_accents(series_name))
    if _useful(series):
        return series, True
    if not ok:
        return None, False
    return not_found_sentinel(), True


def fetch(path: str, series_name: str, volume, cached_series=None):
    """Renvoie (volume_data, network_ok, series_data).

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
    # plus courte, est traite comme absent : cf. is_stale_not_found).
    if cached_series is not None and not is_stale_not_found(cached_series):
        cached = None if cached_series.get("not_found") else cached_series
        if _useful(cached):
            out = dict(cached)
            out.setdefault("source", "series")
            return out, True, None
        return None, network_ok, None

    series, ok = _search_series_sources(query_name)
    if not ok:
        network_ok = False
    if _useful(series):
        return dict(series), True, series
    series_data = not_found_sentinel() if ok else None
    return None, network_ok, series_data
