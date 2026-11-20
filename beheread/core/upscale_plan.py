"""Upscaling des pages : decisions pures, sans Qt ni disque.

L'upscaling (voir infra/upscaler.py) rend nettes les pages de faible
definition, celles que le lecteur devrait sinon agrandir lui-meme (Billy Bat :
1400 px de haut affiches sur 1800 px physiques). Ce module decide quelles
pages en ont besoin, a quelle taille garder le resultat, dans quel ordre les
preparer pendant la lecture et quels fichiers retirer du cache disque."""

from __future__ import annotations

from collections.abc import Iterable

# facteur du modele (Real-ESRGAN AnimeVideo v3 x2)
MODEL_SCALE = 2
# en dessous de cet agrandissement, la page affichee est deja nette : un
# upscaling couterait du calcul pour une difference invisible
MIN_GAIN = 1.15
# pages preparees devant la page courante (sens des index croissants : c'est
# l'ordre de lecture quel que soit le sens manga), et derriere elle
AHEAD = 8
BEHIND = 2
# taille maximale du cache disque des pages ameliorees
CACHE_LIMIT_BYTES = 2 * 1024 ** 3


def display_gain(src_w: int, src_h: int, screen_w: int, screen_h: int,
                 fit_width: bool) -> float:
    """Agrandissement qu'appliquerait le lecteur a une page de src_w x src_h
    sur un ecran de screen_w x screen_h pixels physiques (ajustement a la
    hauteur, ou a la largeur). 0 pour une taille inconnue."""
    if src_w <= 0 or src_h <= 0 or screen_w <= 0 or screen_h <= 0:
        return 0.0
    if fit_width:
        return screen_w / src_w
    return min(screen_h / src_h, screen_w / src_w)


def needs_upscale(gain: float) -> bool:
    return gain >= MIN_GAIN


def stored_size(src_w: int, src_h: int, gain: float) -> tuple[int, int]:
    """Taille a laquelle garder une page amelioree : celle de l'affichage,
    jamais plus que la sortie du modele. Garder la sortie x2 entiere
    quadruplerait la memoire et le disque pour des pixels jamais affiches."""
    factor = max(1.0, min(float(MODEL_SCALE), gain))
    return max(1, round(src_w * factor)), max(1, round(src_h * factor))


def preparation_order(current: Iterable[int], total: int, ahead: int = AHEAD,
                      behind: int = BEHIND) -> list[int]:
    """Pages a preparer, la plus urgente d'abord : celles affichees, puis les
    suivantes, puis quelques precedentes (retour en arriere)."""
    shown = sorted({i for i in current if 0 <= i < total})
    if not shown:
        return []
    order = list(shown)
    last, first = shown[-1], shown[0]
    order += [i for i in range(last + 1, min(total, last + 1 + ahead)) if i not in order]
    order += [i for i in range(first - 1, max(-1, first - 1 - behind), -1) if i not in order]
    return order


def next_batch(current: Iterable[int], total: int, ready: set[int],
               ahead: int = AHEAD, extend: int = 2 * AHEAD,
               behind: int = BEHIND) -> list[int]:
    """Pages du prochain lot a confier au moteur, ou [] s'il n'y a rien a
    lancer. Chaque lancement du moteur coute plusieurs secondes de
    demarrage (pilote graphique, modele) : on attend qu'une page manque dans
    la fenetre de preparation (`ahead` pages devant), puis on prepare d'un
    coup tout ce qui manque jusqu'a `extend` pages devant. `ready` : pages
    deja ameliorees, en cours, ou sans besoin d'amelioration."""
    shown = list(current)
    window = preparation_order(shown, total, ahead, behind)
    if all(i in ready for i in window):
        return []
    return [i for i in preparation_order(shown, total, extend, behind) if i not in ready]


def files_to_evict(files: Iterable[tuple[str, int, float]],
                   limit: int = CACHE_LIMIT_BYTES) -> list[str]:
    """Fichiers (chemin, taille, date d'acces) a supprimer pour ramener le
    cache sous `limit` : les moins recemment utilises d'abord."""
    entries = sorted(files, key=lambda f: f[2])
    total = sum(size for _path, size, _when in entries)
    evict = []
    for path, size, _when in entries:
        if total <= limit:
            break
        evict.append(path)
        total -= size
    return evict
