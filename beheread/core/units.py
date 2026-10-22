"""Tomes et chapitres d'une serie (logique pure, sans Qt).

Dans une serie mixte, les chapitres COMPLETENT les tomes : les tomes parus
viennent d'abord, puis les chapitres qui vont au-dela du dernier tome
possede (« Chainsaw Man » : tomes 1 a 22, puis chapitres 211 a 232). Une
serie peut aussi n'etre faite que de chapitres (scans, webtoons).

La nature d'un numero vient du nom de fichier (series.parse_series_ex) ;
un numero sans marqueur (« Erased 01 ») est un tome, sauf dans une serie
qui n'a que des chapitres explicites. L'utilisateur peut forcer la nature
de toute une serie (« Publiée en » : tomes ou chapitres).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from beheread.core.models import Number
from beheread.i18n import N_, tr, trn

VOLUME, CHAPTER = "volume", "chapter"
# chapitre deja contenu dans un tome possede (d'apres le decoupage officiel,
# voir covered_chapters) : redondant, hors du parcours de lecture et des
# comptes, masque par defaut
COVERED = "covered"

# un tome ordinaire compte ~200 pages ; au-dela de cette moyenne, les tomes
# d'une serie sont ceux d'une edition regroupee (integrale, tomes doubles) :
# le nombre de tomes parus trouve en ligne ne vaut pas pour elle
LARGE_VOLUME_PAGES = 320

# nature de publication d'une serie, choisie par l'utilisateur
AUTO, VOLUMES, CHAPTERS = "auto", "volumes", "chapters"
NATURES = [(AUTO, N_("Automatique")), (VOLUMES, N_("Tomes")), (CHAPTERS, N_("Chapitres"))]

# natures de numero qui font partie du parcours tomes -> chapitres ; un
# cycle (« Seuls Cycle 2 ») ou une plage de tomes (« Kingdom 01-05 ») garde
# sa nature et ne s'enchaine qu'avec ses semblables
_NUMBERED = ("volume", "bare", "chapter")


def classifier(kinds: Iterable[Optional[str]], nature: str = AUTO):
    """Fonction kind -> unite pour une serie dont les fichiers ont les
    natures `kinds` : VOLUME ou CHAPTER, la nature elle-meme pour un cycle
    ou une plage, None pour un fichier sans numero."""
    if nature in (VOLUMES, CHAPTERS):
        forced = VOLUME if nature == VOLUMES else CHAPTER
        return lambda kind: forced if kind in _NUMBERED else kind
    kinds = set(kinds)
    bare = CHAPTER if "chapter" in kinds and "volume" not in kinds else VOLUME
    units = {"volume": VOLUME, "chapter": CHAPTER, "bare": bare}
    return lambda kind: units.get(kind, kind)


def is_chapter(unit: Optional[str]) -> bool:
    """Chapitre, redondant ou non (comptes « 22 chapitres »)."""
    return unit in (CHAPTER, COVERED)


def label_kind(kind: Optional[str], unit: Optional[str]) -> Optional[str]:
    """Nature a afficher (series.volume_label) : celle de l'unite retenue,
    pour qu'un numero nu range parmi les chapitres s'affiche « Chapitre »."""
    if unit in (CHAPTER, COVERED):
        return "chapter"
    if unit == VOLUME:
        return "volume"
    return kind


def order_key(unit: Optional[str], number) -> tuple:
    """Cle de l'ordre de lecture dans une serie : sans numero d'abord (comme
    jusqu'ici), puis les tomes, puis les chapitres qui les completent."""
    if number is None:
        return (0, 0)
    return (2 if unit in (CHAPTER, COVERED) else 1, number)


def next_in_series(current, items) -> Optional[object]:
    """Element suivant `current` dans l'ordre de lecture : le tome de numero
    immediatement superieur, ou apres le dernier tome le premier chapitre ;
    un chapitre est suivi du chapitre suivant. `items` : [(id, unit,
    numero)] de la serie, `current` compris (id compare par egalite). Un
    cycle ou une plage n'est suivi que d'un element de meme nature."""
    by_id = {i: (u, n) for i, u, n in items}
    if current not in by_id:
        return None
    unit, number = by_id[current]
    if unit is None or number is None:
        return None
    path = (VOLUME, CHAPTER)
    same_path = (lambda u: u in path) if unit in path else (lambda u: u == unit)
    here = order_key(unit, number)
    later = [(order_key(u, n), i) for i, u, n in items
             if n is not None and same_path(u) and order_key(u, n) > here]
    return min(later, key=lambda c: c[0])[1] if later else None


def covered_chapters(chapters: Iterable[Number], volumes: Iterable[Number],
                     ranges: Optional[dict]) -> set:
    """Chapitres (parmi `chapters`) deja contenus dans un tome possede
    (`volumes`), d'apres le decoupage officiel `ranges` : {numero de tome
    (texte): [premier, dernier chapitre]} (voir infra.mangadex.chapter_ranges)."""
    if not ranges:
        return set()
    spans = []
    for v in volumes:
        span = ranges.get(fmt_number(v))
        if isinstance(span, (list, tuple)) and len(span) == 2:
            spans.append(span)
    return {c for c in chapters if any(a <= c <= b for a, b in spans)}


@dataclass(frozen=True)
class SeriesCounts:
    """Contenu et avancement d'une serie, tomes et chapitres a part."""

    volumes: int = 0                 # tout ce qui n'est pas un chapitre
    chapters: int = 0
    volumes_read: int = 0
    chapters_read: int = 0
    first_chapter: Optional[Number] = None
    last_chapter: Optional[Number] = None
    current_chapter: Optional[Number] = None   # chapitre entame le plus avance

    @property
    def total(self) -> int:
        return self.volumes + self.chapters

    @property
    def read(self) -> int:
        return self.volumes_read + self.chapters_read


def series_counts(items: Iterable[Tuple[Optional[str], Optional[Number], bool, bool]]
                  ) -> SeriesCounts:
    """`items` : [(unite, numero, termine, entame)] des elements de la serie."""
    volumes = chapters = volumes_read = chapters_read = 0
    numbers: List[Number] = []
    current: Optional[Number] = None
    for unit, number, finished, started in items:
        if unit == COVERED:
            continue
        if unit == CHAPTER:
            chapters += 1
            chapters_read += bool(finished)
            if number is not None:
                numbers.append(number)
                if started and not finished and (current is None or number > current):
                    current = number
        else:
            volumes += 1
            volumes_read += bool(finished)
    return SeriesCounts(volumes, chapters, volumes_read, chapters_read,
                        min(numbers, default=None), max(numbers, default=None), current)


def fmt_number(number) -> str:
    """« 211 », « 385.5 »."""
    if isinstance(number, float) and number.is_integer():
        number = int(number)
    return str(number)


def chapter_range_text(first, last) -> str:
    """« ch. 211 à 232 » (« ch. 211 » pour un seul)."""
    if first == last:
        return tr("ch. {n}", n=fmt_number(first))
    return tr("ch. {first} à {last}", first=fmt_number(first), last=fmt_number(last))


def progress_text(c: SeriesCounts) -> str:
    """Ligne d'avancement d'une pile de serie dans la grille."""
    if c.total and c.read == c.total:
        return tr("Série terminée")
    if not c.chapters:
        if c.volumes_read:
            return tr("{read}/{count} tomes lus", read=c.volumes_read, count=c.volumes)
        return tr("{n} tomes", n=c.volumes)
    if not c.volumes:
        if c.chapters_read or c.current_chapter is not None:
            return tr("{read}/{count} chapitres lus", read=c.chapters_read, count=c.chapters)
        return trn(c.chapters, "{n} chapitre", "{n} chapitres")
    if not c.read and c.current_chapter is None:
        return (trn(c.volumes, "{n} tome", "{n} tomes") + " + "
                + trn(c.chapters, "{n} chapitre", "{n} chapitres"))
    head = (tr("Tomes lus") if c.volumes_read == c.volumes
            else tr("Tome {read}/{count}", read=c.volumes_read, count=c.volumes))
    if c.current_chapter is not None:
        tail = tr("chapitre {n} en cours", n=fmt_number(c.current_chapter))
    elif c.chapters_read:
        tail = tr("{read}/{count} chapitres", read=c.chapters_read, count=c.chapters)
    elif c.first_chapter is not None:
        tail = tr("puis {chapters}",
                  chapters=chapter_range_text(c.first_chapter, c.last_chapter))
    else:
        tail = trn(c.chapters, "{n} chapitre", "{n} chapitres")
    return f"{head} · {tail}"


def count_text(volumes: int, chapters: int) -> str:
    """« 22 tomes · 22 chapitres » (compteur de la grille)."""
    parts = []
    if volumes or not chapters:
        parts.append(trn(volumes, "{n} tome", "{n} tomes"))
    if chapters:
        parts.append(trn(chapters, "{n} chapitre", "{n} chapitres"))
    return " · ".join(parts)


def missing_chapters(numbers: Iterable, start: Optional[int] = None) -> List[int]:
    """Chapitres manquants parmi les entiers, de `start` jusqu'au dernier
    possede. `start` : 1 pour une serie en chapitres seuls, le chapitre qui
    suit le dernier tome possede d'une serie mixte (decoupage officiel connu,
    voir coverage_end), sinon (None) le premier chapitre possede - ceux
    d'avant sont dans les tomes. Un chapitre bonus (« 12.5 ») ne cree pas de
    trou."""
    owned = {int(n) for n in numbers
             if isinstance(n, (int, float)) and not isinstance(n, bool)
             and float(n).is_integer() and n >= 1}
    if not owned:
        return []
    first = min(owned) if start is None else start
    return [n for n in range(first, max(owned) + 1) if n not in owned]


def volume_of(number, ranges: Optional[dict]):
    """Tome officiel qui contient le chapitre `number` d'apres le decoupage
    `ranges` ({tome: [premier, dernier chapitre]}), ou None."""
    if number is None or not ranges:
        return None
    for volume, span in ranges.items():
        if isinstance(span, (list, tuple)) and len(span) == 2 and span[0] <= number <= span[1]:
            try:
                return int(float(volume))
            except (TypeError, ValueError):
                return None
    return None


def coverage_end(volumes: Iterable[Number], ranges: Optional[dict]) -> Optional[Number]:
    """Dernier chapitre du dernier tome possede `volumes`, d'apres le
    decoupage officiel `ranges`, ou None s'il ne connait pas ce tome-la : un
    decoupage lacunaire (tomes recents absents) ferait sinon compter comme
    manquants des chapitres deja contenus dans les tomes."""
    volumes = [v for v in volumes if isinstance(v, (int, float))]
    if not ranges or not volumes:
        return None
    span = ranges.get(fmt_number(max(volumes)))
    return span[1] if isinstance(span, (list, tuple)) and len(span) == 2 else None
