"""Politique du cache hors ligne : quels tomes garder sur l'appareil pour
lire sans connexion au serveur. Logique pure (aucune dependance Qt, testee
isolement), partagee par le desktop et le serveur Beheread (qui la calcule
pour les clients web).

Pour chaque serie en cours - meme definition que « Continuer la lecture »
(voir library_model.continue_reading) - on garde le tome N (en cours, ou le
suivant a lire), le tome N+1 et le tome N-1, dans l'ordre de lecture de la
serie (tomes, puis les chapitres qui les completent).

Le budget est rempli par priorite : d'abord les tomes N de toutes les
series (de la plus recemment lue a la plus ancienne), puis les N+1, puis
les N-1. Un tome qui ne tient plus dans le budget est saute, mais un tome
plus petit qui vient apres peut encore y entrer. Un tome de taille inconnue
est garde sans etre compte.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from beheread.core import library_model, units
from beheread.core.models import VolumeInfo

GB = 1024 ** 3
# budgets par defaut (reglables)
DESKTOP_BUDGET = 10 * GB
WEB_BUDGET = 3 * GB


def _series_order(infos: List[VolumeInfo]) -> Dict[str, List[VolumeInfo]]:
    """Tomes de chaque serie dans l'ordre de lecture (sans les chapitres
    deja contenus dans un tome possede)."""
    groups: Dict[str, List[VolumeInfo]] = {}
    for info in infos:
        if info.series_key and info.unit != units.COVERED:
            groups.setdefault(info.series_key, []).append(info)
    for vols in groups.values():
        vols.sort(key=library_model.volume_order)
    return groups


def volumes_to_keep(infos: Iterable[VolumeInfo], sizes: Optional[Dict[str, int]] = None,
                    budget: Optional[int] = None,
                    dismissed: Optional[dict] = None) -> List[str]:
    """Empreintes des tomes a garder hors ligne, par priorite decroissante.

    `sizes` : {empreinte: octets} (taille du fichier d'origine sur le desktop,
    des pages preparees pour le web) ; `budget` : octets disponibles, None
    pour ne pas limiter ; `dismissed` : tomes masques de « Continuer la
    lecture » (leur serie n'est alors pas « en cours »)."""
    infos = list(infos)
    sizes = sizes or {}
    current = library_model.continue_reading(infos, dismissed, limit=len(infos))
    groups = _series_order(infos)

    tiers: List[List[VolumeInfo]] = [[], [], []]   # N, N+1, N-1
    for info, _kind in current:
        tiers[0].append(info)
        vols = groups.get(info.series_key or "")
        if not vols or info not in vols:
            continue   # tome isole : pas de voisins
        i = vols.index(info)
        if i + 1 < len(vols):
            tiers[1].append(vols[i + 1])
        if i > 0:
            tiers[2].append(vols[i - 1])

    kept: List[str] = []
    seen = set()
    used = 0
    for tier in tiers:
        for info in tier:
            if info.key in seen:
                continue
            size = sizes.get(info.key)
            if budget is not None and size is not None and used + size > budget:
                continue
            seen.add(info.key)
            kept.append(info.key)
            used += size or 0
    return kept
