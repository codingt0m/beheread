"""Logique pure de la bibliotheque (aucune dependance Qt, testee isolement) :
statut de lecture d'un tome ou d'une serie, cles de tri, et selection des
tomes de la bande « Continuer la lecture ».

Les fonctions travaillent sur des VolumeInfo / SeriesInfo (voir models.py),
prepares par la bibliotheque (LibraryWidget._entry_info).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple, Union

from beheread.core.models import SeriesInfo, VolumeInfo

UNREAD, READING, FINISHED = "unread", "reading", "finished"
ALL = "all"

STATUS_FILTERS = [(ALL, "Tous"), (UNREAD, "Non lus"), (READING, "En cours"),
                  (FINISHED, "Terminés")]
STATUS_LABELS = {UNREAD: "Non lu", READING: "En cours", FINISHED: "Terminé"}

SORTS = [("title", "Titre"), ("added", "Ajout récent"), ("read", "Lu récemment"),
         ("author", "Auteur"), ("year", "Année de sortie")]
SORT_KEYS = {k for k, _ in SORTS}

CONTINUE_LIMIT = 12

# un tome referme sur l'une de ses premieres pages n'est pas « commence »
# (couverture, page de garde, sommaire) : sa progression est effacee a la
# sortie du lecteur (voir SessionMixin.release)
STARTED_MIN_PAGE = 3   # indice de page (0 = premiere page) : page 4 et au-dela


def is_started(page) -> bool:
    """Vrai si la lecture a depasse les premieres pages du tome."""
    return (page or 0) >= STARTED_MIN_PAGE


def volume_status(progress) -> str:
    """Statut d'un tome d'apres sa progression (page, total, termine) ou None.
    Un tome referme sur l'une de ses trois premieres pages reste « non lu »."""
    if not progress:
        return UNREAD
    page, _total, finished = progress
    if finished:
        return FINISHED
    return READING if is_started(page) else UNREAD


def series_status(statuses: Iterable[str]) -> str:
    """Statut agrege d'une serie : terminee si tous ses tomes le sont, en
    cours des qu'un tome est entame ou termine, non lue sinon."""
    statuses = list(statuses)
    if statuses and all(s == FINISHED for s in statuses):
        return FINISHED
    if any(s in (READING, FINISHED) for s in statuses):
        return READING
    return UNREAD


def matches_status(status: str, wanted: str) -> bool:
    return wanted == ALL or status == wanted


def natural_key(text: str) -> tuple:
    """Cle de tri « naturelle » : les nombres comparés par valeur (« Tome 2 »
    avant « Tome 10 »), le reste sans tenir compte de la casse."""
    parts = re.split(r"(\d+)", (text or "").casefold())
    return tuple(int(p) if i % 2 else p for i, p in enumerate(parts))


def sort_key(sort: str, info: Union[VolumeInfo, SeriesInfo]) -> tuple:
    """Cle de tri croissante pour le critere `sort`. Les valeurs inconnues
    (auteur ou annee absents, jamais lu) sont toujours rangees en dernier ;
    le titre departage les ex aequo."""
    title = natural_key(info.title)
    if sort == "added":
        return (-(info.added or 0), title)
    if sort == "read":
        last = info.last_read or 0
        return (0 if last else 1, -last, title)
    if sort == "author":
        author = (info.author or "").casefold()
        return (0 if author else 1, author, title)
    if sort == "year":
        year = info.year
        return (0 if year else 1, year or 0, title)
    return (title,)


def aggregate_series_info(title: str, infos: Iterable[VolumeInfo]) -> SeriesInfo:
    """Info d'un dossier de serie pour le tri : ajout et lecture les plus
    recents, premiere annee connue, premier auteur connu."""
    infos = list(infos)
    years = [i.year for i in infos if i.year]
    authors = [i.author for i in infos if i.author]
    return SeriesInfo(
        title=title,
        status=series_status(i.status for i in infos),
        added=max((i.added or 0 for i in infos), default=0),
        last_read=max((i.last_read or 0 for i in infos), default=0),
        author=authors[0] if authors else "",
        year=min(years) if years else None,
    )


def _volume_order(info: VolumeInfo):
    return (info.volume if info.volume is not None else -1, info.title.casefold())


def continue_reading(infos: Iterable[VolumeInfo], dismissed: Optional[dict] = None,
                     limit: int = CONTINUE_LIMIT) -> List[Tuple[VolumeInfo, str]]:
    """Tomes a proposer dans « Continuer la lecture », du plus recent au plus
    ancien : liste de (info, kind) avec kind = "reading" (tome entame) ou
    "next" (tome suivant, pas encore commence, d'une serie dont le dernier
    tome lu est termine).

    `dismissed` : {empreinte: horodatage} des tomes masques par l'utilisateur ;
    un tome masque reapparait des qu'il est relu apres ce masquage."""
    infos = list(infos)
    dismissed = dismissed or {}
    candidates = []   # (horodatage d'activite, info, kind)

    def visible(info, activity):
        return activity > dismissed.get(info.key, 0)

    for info in infos:
        if info.status == READING and info.last_read:
            if visible(info, info.last_read):
                candidates.append((info.last_read, info, "reading"))

    groups = {}
    for info in infos:
        if info.series_key:
            groups.setdefault(info.series_key, []).append(info)
    for vols in groups.values():
        if len(vols) < 2 or any(v.status == READING for v in vols):
            continue   # tome deja propose comme « en cours »
        vols.sort(key=_volume_order)
        read = [v for v in vols if v.last_read]
        if not read:
            continue
        latest = max(read, key=lambda v: v.last_read)
        if latest.status != FINISHED:
            continue
        idx = vols.index(latest)
        nxt = next((v for v in vols[idx + 1:] if v.status == UNREAD), None)
        if nxt is not None and visible(nxt, latest.last_read):
            candidates.append((latest.last_read, nxt, "next"))

    candidates.sort(key=lambda c: -c[0])
    return [(info, kind) for _ts, info, kind in candidates[:limit]]
