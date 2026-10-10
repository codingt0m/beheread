"""Lien vers Babelio depuis la fiche de fin de tome (logique pure, sans Qt).

Babelio n'a pas d'API publique et ses CGU interdisent la collecte
automatisee : Beheread n'y publie rien. Il ouvre, dans le navigateur de
l'utilisateur, la recherche Babelio du tome qu'il vient de finir ; c'est lui
qui le marque « lu » sur son compte, depuis sa propre session.

La recherche de Babelio est un formulaire POST (recherche.php, champ
« Recherche ») : un lien ne suffit pas. On ecrit donc une petite page locale
qui soumet ce formulaire a l'ouverture, depuis le navigateur.
"""

import html

from beheread.core.series import clean_title, normalize_name, parse_series_ex

SEARCH_URL = "https://www.babelio.com/recherche.php"
SEARCH_FIELD = "Recherche"

_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Beheread · Babelio</title></head>
<body onload="document.forms[0].submit()">
<form method="post" action="{action}">
<input type="hidden" name="{field}" value="{query}">
<noscript><button type="submit">Rechercher « {query} » sur Babelio</button></noscript>
</form>
<p>Ouverture de Babelio…</p>
</body></html>
"""


def search_query(stem, folder=None, series_name=None):
    """Texte a chercher pour un tome : « Berserk tome 3 » pour un tome numerote
    (chapitres et cycles : la serie seule, Babelio ne les catalogue pas), le
    titre nettoye pour un fichier sans numero (one-shot). `series_name`
    remplace le nom detecte (regroupement force par l'utilisateur)."""
    name, number, kind = parse_series_ex(stem, folder)
    if series_name:
        name = series_name
    if number is None or kind is None:
        return series_name or clean_title(stem)
    if kind not in ("volume", "bare"):
        return name
    if isinstance(number, float) and number.is_integer():
        number = int(number)
    return f"{name} tome {number}"


def search_page(query) -> str:
    """Page HTML qui envoie `query` a la recherche de livres de Babelio.

    La requete est ramenee a des mots sans accents ni ponctuation : le jeu de
    caracteres attendu par Babelio n'est pas documente, et sa recherche ne
    tient pas compte des accents."""
    return _PAGE.format(action=SEARCH_URL, field=SEARCH_FIELD,
                        query=html.escape(normalize_name(query), quote=True))
