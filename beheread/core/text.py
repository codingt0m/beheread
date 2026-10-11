"""Normalisation de texte partagee par la detection des series, la recherche
et les metadonnees (logique pure, testee isolement) : retrait des accents et
noms qui ne designent pas une serie."""

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
