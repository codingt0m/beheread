"""Normalisation de texte partagee par la detection des series, la recherche
et les metadonnees (logique pure, testee isolement) : retrait des accents et
noms qui ne designent pas une serie."""

import html
import re
import unicodedata

# noms qui ne sont pas des noms de serie : un fichier nomme seulement
# « Tome 01 » ou « Volume 1 » tire son nom de serie de son dossier (voir
# series.parse_series_ex) et n'est jamais cherche en ligne (sinon AniList
# trouve « Full Volume »). Compares a une forme normalisee (minuscules, sans
# accents ni ponctuation).
GENERIC_NAMES = frozenset({
    "", "tome", "tomes", "tomo", "volume", "volumes", "vol", "t", "v",
    "chapitre", "chapter", "chap", "ch", "episode", "ep", "cycle",
    "integrale", "n", "no", "book", "livre", "manga", "bd", "scan", "scans"})


def strip_accents(text: str, compat: bool = True) -> str:
    """Retire accents et diacritiques (« Pokémon » -> « Pokemon »).

    compat=True : decomposition NFKD, qui ramene aussi les formes de
    compatibilite (pleine chasse, ligatures, exposants) - pour la recherche et
    les requetes en ligne. compat=False : decomposition NFD seule, forme des
    cles de serie (series.normalize_name) : ces cles sont enregistrees en base
    (noms de serie, sens de lecture, associations AniList) et ne doivent pas
    changer."""
    if compat:
        decomposed = unicodedata.normalize("NFKD", text or "")
        return "".join(c for c in decomposed if not unicodedata.combining(c))
    decomposed = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


_TAG = re.compile(r"<[^>]+>")
_SOURCE_NOTE = re.compile(r"\(\s*(?:source|sources)\s*:[^)]*\)\s*$", re.I)
_BLANK_LINES = re.compile(r"\n\s*\n+")


def clean_description(text) -> str:
    """Resume d'une oeuvre venu d'une base en ligne, en texte brut : balises
    (<br>, <i>...) retirees, entites decodees, mention finale « (Source :
    ...) » retiree, paragraphes resserres."""
    if not isinstance(text, str):
        return ""
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = html.unescape(_TAG.sub("", text)).replace("\r", "")
    text = _BLANK_LINES.sub("\n\n", text.strip())
    return _SOURCE_NOTE.sub("", text).strip()


# genres des bases en ligne (AniList, MangaDex : en anglais) -> francais
GENRES_FR = {
    "action": "Action", "adventure": "Aventure", "boys' love": "Boys' love",
    "comedy": "Comédie", "crime": "Policier", "drama": "Drame", "ecchi": "Ecchi",
    "fantasy": "Fantasy", "girls' love": "Girls' love", "historical": "Historique",
    "horror": "Horreur", "isekai": "Isekai", "magical girls": "Magical girl",
    "mahou shoujo": "Magical girl", "mecha": "Mecha", "medical": "Médical",
    "music": "Musique", "mystery": "Mystère", "philosophical": "Philosophique",
    "psychological": "Psychologique", "romance": "Romance", "sci-fi": "Science-fiction",
    "slice of life": "Tranche de vie", "sports": "Sport", "superhero": "Super-héros",
    "supernatural": "Surnaturel", "thriller": "Thriller", "tragedy": "Tragédie",
    "wuxia": "Wuxia", "hentai": "Hentai",
}


def genre_fr(name) -> str:
    """Nom francais d'un genre (le nom d'origine s'il est inconnu)."""
    if not isinstance(name, str):
        return ""
    return GENRES_FR.get(name.strip().casefold(), name.strip())
