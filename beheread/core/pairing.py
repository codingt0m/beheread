"""Logique pure d'appairage des pages en mode double page (aucune dependance
Qt). Extraite du lecteur pour etre testable isolement : c'est la partie la plus
subtile de la navigation (parite de l'appairage, planches doubles, recul).

Une "planche double" (spread) est une image deja plus large que haute : elle
couvre a elle seule une double page et ne doit jamais etre couplee a sa
voisine. `is_spread` est un predicat index -> bool fourni par l'appelant.
"""


def segment_start(page, is_spread):
    """Page qui suit la derniere planche double precedant `page` (debut de la
    section ou l'appairage se recale), ou 0 s'il n'y en a pas."""
    for i in range(page - 1, -1, -1):
        if is_spread(i):
            return i + 1
    return 0


def pair_anchor(page, page_offset, is_spread, shifted=()):
    """Premiere page de l'appairage dont releve `page` : celle qui suit la
    derniere planche double qui la precede - dans le livre imprime, une
    planche double termine toujours une double page, la suivante en commence
    une nouvelle -, sinon le decalage de parite choisi (touche S). Le lecteur
    se recale ainsi de lui-meme apres chaque planche double.

    `shifted` : debuts de section (voir segment_start) dont l'appairage a ete
    decale a la main (touche S apres une planche double) - la page qui suit la
    planche y reste seule et l'appairage commence a la suivante."""
    start = segment_start(page, is_spread)
    if start == 0:
        return page_offset
    return start + (1 if start in shifted else 0)


def pairs_with_next(page, total, page_offset, double_page, is_spread, shifted=()):
    """La page `page` forme-t-elle une paire avec `page + 1` ? Depend du mode
    double page, du decalage de parite (touche S) et des planches doubles."""
    return (double_page and 0 <= page and page + 1 < total
            and not is_spread(page) and not is_spread(page + 1)
            and (page - pair_anchor(page, page_offset, is_spread, shifted)) % 2 == 0)


def current_indices(page, total, page_offset, double_page, is_spread, shifted=()):
    """Indices de page(s) affiche(s) pour la position courante : une paire
    [page, page+1] ou une page seule [page]."""
    if pairs_with_next(page, total, page_offset, double_page, is_spread, shifted):
        return [page, page + 1]
    return [page]


def step_back(page, total, page_offset, double_page, is_spread, shifted=()):
    """Nombre de pages a reculer pour atteindre la page/paire logique
    precedente, en tenant compte de la parite et des planches doubles."""
    if not double_page:
        return 1
    prev_index = page - 1
    if prev_index <= 0:
        return 1
    if pairs_with_next(prev_index - 1, total, page_offset, double_page, is_spread, shifted):
        return 2
    return 1
