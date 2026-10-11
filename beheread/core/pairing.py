"""Logique pure d'appairage des pages en mode double page (aucune dependance
Qt). Extraite du lecteur pour etre testable isolement : c'est la partie la plus
subtile de la navigation (parite de l'appairage, planches doubles, recul).

Une "planche double" (spread) est une image deja plus large que haute : elle
couvre a elle seule une double page et ne doit jamais etre couplee a sa
voisine. `is_spread` est un predicat index -> bool fourni par l'appelant.
"""


def pair_anchor(page, page_offset, is_spread):
    """Premiere page de l'appairage dont releve `page` : celle qui suit la
    derniere planche double qui la precede - dans le livre imprime, une
    planche double termine toujours une double page, la suivante en commence
    une nouvelle -, sinon le decalage de parite choisi (touche S). Le lecteur
    se recale ainsi de lui-meme apres chaque planche double."""
    for i in range(page - 1, -1, -1):
        if is_spread(i):
            return i + 1
    return page_offset


def pairs_with_next(page, total, page_offset, double_page, is_spread):
    """La page `page` forme-t-elle une paire avec `page + 1` ? Depend du mode
    double page, du decalage de parite (touche S) et des planches doubles."""
    return (double_page and 0 <= page and page + 1 < total
            and not is_spread(page) and not is_spread(page + 1)
            and (page - pair_anchor(page, page_offset, is_spread)) % 2 == 0)


def current_indices(page, total, page_offset, double_page, is_spread):
    """Indices de page(s) affiche(s) pour la position courante : une paire
    [page, page+1] ou une page seule [page]."""
    if pairs_with_next(page, total, page_offset, double_page, is_spread):
        return [page, page + 1]
    return [page]


def step_back(page, total, page_offset, double_page, is_spread):
    """Nombre de pages a reculer pour atteindre la page/paire logique
    precedente, en tenant compte de la parite et des planches doubles."""
    if not double_page:
        return 1
    prev_index = page - 1
    if prev_index <= 0:
        return 1
    if pairs_with_next(prev_index - 1, total, page_offset, double_page, is_spread):
        return 2
    return 1
