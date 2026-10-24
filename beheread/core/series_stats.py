"""Statistiques d'une serie : logique pure (aucune dependance Qt, testee
isolement), dessinee par ui/series_stats_view.py.

Une serie n'existe pas dans le journal de lecture : il ne connait que des
tomes (empreintes de contenu). La bibliotheque fournit donc un instantane de
la serie telle qu'elle est regroupee aujourd'hui (SeriesHoldings : ses tomes
et chapitres, possedes ou manquants, avec leur progression), et le rapport
croise cet instantane avec les lignes du journal de ces tomes
(ReadingLog.series_rows).

Contrairement a la vue generale, le rapport couvre tout l'historique de la
serie : elle se lit sur une duree finie, sans periode a choisir.
"""

import datetime as _dt
from dataclasses import dataclass
from typing import Optional

from beheread.core import stats, units

FINISHED, READING, UNREAD, MISSING = "finished", "reading", "unread", "missing"

# fins de tome prises en compte pour estimer la date de fin de la serie
PROJECTION_DAYS = 90
SPARK_MONTHS = 12

_DAY = _dt.timedelta(days=1)


@dataclass(frozen=True)
class SeriesItem:
    """Un tome (ou chapitre) de la serie, possede ou non."""
    number: object                  # numero, None si le fichier n'en a pas
    unit: str = units.VOLUME        # units.VOLUME, units.CHAPTER...
    volume: Optional[str] = None    # empreinte de contenu, None si non possede
    status: str = UNREAD            # FINISHED, READING, UNREAD ou MISSING
    page: int = 0                   # page atteinte (0 = premiere)
    total: int = 0                  # nombre de pages, 0 si inconnu
    title: str = ""


@dataclass(frozen=True)
class SeriesHoldings:
    """Instantane d'une serie fourni par la bibliotheque."""
    key: str
    name: str
    author: str = ""
    published: Optional[int] = None   # tomes parus, None si inconnu
    items: tuple = ()                 # SeriesItem dans l'ordre de lecture

    @property
    def owned(self) -> list:
        return [i for i in self.items if i.status != MISSING]


def item_order(item: SeriesItem) -> tuple:
    """Ordre de lecture (units.order_key), les manquants a leur place."""
    return units.order_key(item.unit, item.number)


@dataclass(frozen=True)
class VolumeStat:
    item: SeriesItem
    pages: int = 0
    seconds: float = 0.0
    finished_on: Optional[_dt.date] = None   # premiere fin de lecture dans le journal


@dataclass(frozen=True)
class SeriesReport:
    holdings: SeriesHoldings
    totals: stats.Totals
    first_day: Optional[_dt.date]     # premier et dernier jour de lecture de la serie
    last_day: Optional[_dt.date]
    months: list                      # stats.Bucket des SPARK_MONTHS derniers mois
    volumes: list                     # VolumeStat, dans l'ordre des items
    base: int                         # tomes termines sans date (avant le journal, marques lus)
    progression: list                 # [(jour, tomes termines cumules, VolumeStat)]
    pace: Optional[float]             # secondes par page : serie, sinon None
    library_pace: Optional[float]     # rythme moyen de toute la lecture
    remaining_seconds: float
    remaining_items: int              # possedes, non termines
    unknown_pages: int                # dont le nombre de pages est inconnu
    recent_finished: int              # fins des PROJECTION_DAYS derniers jours
    projected_end: Optional[_dt.date]
    rank: Optional[int]               # place parmi les series les plus lues (1 = premiere)
    share: float                      # part du temps de lecture total (0 a 1)
    best_day: Optional[stats.Bucket]  # journee de lecture la plus longue
    devices: list                     # [(nom de l'appareil, secondes)], le plus utilise d'abord

    @property
    def finished(self) -> int:
        return sum(1 for v in self.volumes if v.item.status == FINISHED)

    @property
    def owned(self) -> int:
        return len(self.holdings.owned)


def projected_end(remaining: int, recent: int, today: _dt.date,
                  days: int = PROJECTION_DAYS) -> Optional[_dt.date]:
    """Date de fin estimee : les `remaining` tomes au rythme des `recent`
    fins des `days` derniers jours. None sans fin recente (on ne prolonge
    pas une serie en pause) ou sans rien a lire."""
    if not remaining or not recent:
        return None
    return today + _dt.timedelta(days=round(remaining * days / recent))


def build_series_report(log, holdings: SeriesHoldings, today: _dt.date, resolve=None,
                        pace=None, library_pace=None) -> SeriesReport:
    """Rapport d'une serie. `log` : le journal de lecture ; `resolve` : voir
    stats.top_series (rang de la serie) ; `pace` : rythme propre a la serie
    (stats.pace_of), `library_pace` : rythme moyen, repli de l'estimation."""
    keys = [i.volume for i in holdings.items if i.volume]
    rows = log.series_rows(keys) if keys else []
    per_volume: dict = {}     # tome -> [pages, secondes, premiere fin]
    per_day: dict = {}        # jour -> [pages, secondes, fins]
    devices: dict = {}
    days_read, sessions, finishes = set(), 0, 0
    for day, device, volume, pages, seconds, n_sessions, finished in rows:
        v = per_volume.setdefault(volume, [0, 0.0, None])
        v[0] += pages
        v[1] += seconds
        if finished and v[2] is None:
            v[2] = _dt.date.fromisoformat(day)
        d = per_day.setdefault(day, [0, 0.0, 0])
        d[0] += pages
        d[1] += seconds
        d[2] += finished
        if pages:
            days_read.add(day)
        devices[device] = devices.get(device, 0.0) + seconds
        sessions += n_sessions
        finishes += finished

    volumes = []
    for item in holdings.items:
        pages, seconds, done = per_volume.get(item.volume, (0, 0.0, None))
        volumes.append(VolumeStat(item, int(pages), float(seconds),
                                  done if item.status == FINISHED else None))
    chapters = [v for v in volumes if units.is_chapter(v.item.unit)]
    totals = stats.Totals(
        pages=sum(v.pages for v in volumes), seconds=sum(v.seconds for v in volumes),
        sessions=sessions, finished=finishes, active_days=len(days_read),
        volumes=sum(1 for v in volumes if v.pages),
        finished_chapters=sum(1 for v in chapters if v.finished_on),
        chapters=sum(1 for v in chapters if v.pages))

    dated = sorted(((v.finished_on, v) for v in volumes if v.finished_on is not None),
                   key=lambda dv: dv[0])
    base = sum(1 for v in volumes if v.item.status == FINISHED and not v.finished_on)
    progression = [(day, base + i + 1, v) for i, (day, v) in enumerate(dated)]

    rate = pace or library_pace or 0.0
    remaining_pages = unknown = left = 0
    for item in holdings.owned:
        if item.status == FINISHED:
            continue
        left += 1
        if item.total:
            remaining_pages += max(0, item.total - item.page)
        else:
            unknown += 1
    recent = sum(1 for day, _v in dated if (today - day).days < PROJECTION_DAYS)

    read_days = sorted(per_day)
    first = _dt.date.fromisoformat(read_days[0]) if read_days else None
    last = _dt.date.fromisoformat(read_days[-1]) if read_days else None
    spark_start = stats.add_months(today.replace(day=1), 1 - SPARK_MONTHS)
    months: dict = {}
    for day, (pages, seconds, finished) in per_day.items():
        m = months.setdefault(day[:7], [0, 0.0, 0])
        m[0] += pages
        m[1] += seconds
        m[2] += finished
    best = max(per_day.items(), key=lambda kv: (kv[1][1], kv[0]), default=None)

    rank, share = None, 0.0
    if resolve is not None and first is not None:
        ranking = stats.top_series(log.volumes(log.first_day() or first, today), resolve,
                                   n=1 << 30)
        for i, s in enumerate(ranking):
            if s.key == holdings.key:
                rank, share = i + 1, s.share
                break

    return SeriesReport(
        holdings=holdings, totals=totals, first_day=first, last_day=last,
        months=stats.fill_range(spark_start, today, "month",
                                [(k, *v) for k, v in sorted(months.items())]),
        volumes=volumes, base=base, progression=progression,
        pace=pace, library_pace=library_pace,
        remaining_seconds=remaining_pages * rate, remaining_items=left, unknown_pages=unknown,
        recent_finished=recent, projected_end=projected_end(left, recent, today),
        rank=rank, share=share,
        best_day=(stats.Bucket(_dt.date.fromisoformat(best[0]), best[1][0], best[1][1],
                               best[1][2]) if best and best[1][1] > 0 else None),
        devices=sorted(((name, s) for name, s in devices.items() if s > 0),
                       key=lambda d: (-d[1], d[0])))
