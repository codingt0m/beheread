"""Statistiques d'une serie : logique pure (aucune dependance Qt, testee
isolement), dessinee par ui/series_stats_view.py.

Une serie n'existe pas dans le journal de lecture : il ne connait que des
tomes (empreintes de contenu), avec le titre et le nom de serie du moment
de la lecture. La bibliotheque fournit un instantane de la serie telle
qu'elle est regroupee aujourd'hui (SeriesHoldings : son parcours de
lecture, tomes virtuels compris, avec la progression de chacun), et le
rapport le croise avec les lignes du journal :

* celles des tomes de l'instantane (et des chapitres d'un tome virtuel) ;
* celles ecrites sous le nom de la serie : un tome supprime ou remplace par
  un autre fichier garde ses chiffres, rattaches a son numero (lu dans le
  titre journalise).

Seule la lecture compte, jamais la possession. Une ligne (un tome, un jour)
de moins de GLANCE_PAGES pages est un coup d'oeil : son temps reste au
total, mais elle ne fait ni une seance, ni un jour de lecture, ni le rythme.
Un tome n'est « lu dans le lecteur » (temps par tome, records) que si au
moins READ_SHARE de ses pages y ont ete lues : un tome survole puis marque
lu n'a pas de temps de lecture.

Le rapport couvre tout l'historique de la serie : elle se lit sur une duree
finie, sans periode a choisir.
"""

import datetime as _dt
from dataclasses import dataclass
from typing import Optional

from beheread.core import stats, units
from beheread.core.series import normalize_name, parse_series_ex

FINISHED, READING, UNREAD = "finished", "reading", "unread"

GLANCE_PAGES = 10          # meme seuil que ReadingLog.PACE_MIN_PAGES
READ_SHARE = 0.5           # part des pages lues dans le lecteur
UNKNOWN_READ_PAGES = 80    # ... quand le nombre de pages du tome est inconnu


@dataclass(frozen=True)
class SeriesItem:
    """Un tome (ou chapitre) du parcours de lecture de la serie."""
    number: object                  # numero, None si le fichier n'en a pas
    unit: str = units.VOLUME        # units.VOLUME, units.CHAPTER...
    volume: Optional[str] = None    # empreinte de contenu, None pour un tome supprime
    status: str = UNREAD            # FINISHED, READING ou UNREAD
    page: int = 0                   # page atteinte (0 = premiere)
    total: int = 0                  # nombre de pages, 0 si inconnu
    title: str = ""
    aliases: tuple = ()             # empreintes de ses chapitres (tome virtuel)
    covers: tuple = ()              # numeros de ses chapitres (tome virtuel)


@dataclass(frozen=True)
class SeriesHoldings:
    """Instantane d'une serie fourni par la bibliotheque."""
    key: str
    name: str
    author: str = ""
    items: tuple = ()     # SeriesItem dans l'ordre de lecture
    extra: tuple = ()     # empreintes hors parcours (chapitres deja dans un tome)


def item_order(item: SeriesItem) -> tuple:
    return units.order_key(item.unit, item.number)


@dataclass(frozen=True)
class VolumeStat:
    item: SeriesItem
    pages: int = 0                          # pages lues dans le lecteur
    seconds: float = 0.0
    sessions: int = 0                       # seances, hors coups d'oeil
    finished_on: Optional[_dt.date] = None  # premiere fin dans le journal
    read_here: bool = False                 # lu dans le lecteur (voir le module)
    one_sitting: bool = False               # lu en une seule seance

    @property
    def pace(self) -> Optional[float]:
        return self.seconds / self.pages if self.pages and self.seconds else None


@dataclass(frozen=True)
class DayEntry:
    """Un jour de lecture de la serie (au moins une ligne hors coup d'oeil)."""
    day: _dt.date
    seconds: float
    pages: int
    sessions: int
    finished: tuple   # SeriesItem termines ce jour-la
    started: tuple    # SeriesItem commences ce jour-la, pas termines


@dataclass(frozen=True)
class GlanceRun:
    """Jours consecutifs (dans le carnet) de simples coups d'oeil."""
    first: _dt.date
    last: _dt.date
    count: int        # lignes (un tome, un jour)
    seconds: float


@dataclass(frozen=True)
class SeriesReport:
    holdings: SeriesHoldings
    seconds: float                    # tout le temps passe, coups d'oeil compris
    pages: int
    active_days: int                  # jours de lecture (hors coups d'oeil)
    sessions: int                     # seances (hors coups d'oeil)
    first_day: Optional[_dt.date]     # premier et dernier jour de lecture
    last_day: Optional[_dt.date]
    volumes: list                     # VolumeStat du parcours, dans l'ordre de lecture
    journal: list                     # DayEntry et GlanceRun, du plus recent au plus ancien
    pace: Optional[float]             # secondes par page dans la serie
    library_pace: Optional[float]     # rythme moyen de toute la lecture
    remaining_seconds: float
    remaining_items: int
    unknown_pages: int                # titres restants au nombre de pages inconnu
    remaining_days: Optional[float]   # jours de lecture pour finir, a votre rythme
    rank: Optional[int]               # place parmi les series les plus lues (1 = premiere)
    share: float                      # part du temps de lecture total (0 a 1)
    best_day: Optional[DayEntry]
    session_seconds: float            # seance moyenne
    session_pages: float
    devices: list                     # [(nom de l'appareil, secondes)], le plus utilise d'abord

    @property
    def finished(self) -> int:
        return sum(1 for v in self.volumes if v.item.status == FINISHED)

    @property
    def read_here(self) -> list:
        return [v for v in self.volumes if v.read_here]

    def median_seconds(self) -> float:
        times = sorted(v.seconds for v in self.read_here)
        return times[len(times) // 2] if times else 0.0


def collect_rows(log, holdings: SeriesHoldings, owner=None) -> list:
    """Lignes du journal de la serie (voir ReadingLog.series_rows) : ses
    tomes, et ce qui a ete lu sous son nom. `owner(empreinte)` : cle de
    serie actuelle d'un tome de la bibliotheque, ou None - un tome range
    depuis dans une autre serie n'est plus compte ici."""
    keys = {k for i in holdings.items for k in (i.volume, *i.aliases) if k}
    keys.update(holdings.extra)
    wanted = {holdings.key, normalize_name(holdings.name)}
    names = [n for n in log.series_names() if normalize_name(n) in wanted]
    if not keys and not names:
        return []
    return [r for r in log.series_rows(keys, names)
            if r[2] in keys or owner is None or owner(r[2]) in (None, holdings.key)]


def series_seconds(log, holdings: SeriesHoldings, owner=None) -> float:
    """Temps passe dans la serie (panneau d'informations)."""
    return sum(r[4] for r in collect_rows(log, holdings, owner))


class _Slots:
    """Rattache une ligne du journal a un element du parcours : par son
    empreinte, sinon par le numero lu dans son titre (tome supprime ou
    remplace). Un tome supprime sans remplacant devient un element a part ;
    un chapitre inconnu (deja dans un tome) n'est rattache a rien."""

    def __init__(self, items):
        self.by_key, self.by_number, self.orphans = {}, {}, {}
        for item in items:
            for k in (item.volume, *item.aliases):
                if k:
                    self.by_key[k] = item
            if item.number is not None:
                self.by_number.setdefault((units.is_chapter(item.unit), item.number), item)
            for n in item.covers:
                self.by_number.setdefault((True, n), item)

    def find(self, volume, title):
        item = self.by_key.get(volume)
        if item is not None or not title:
            return item
        _name, number, kind = parse_series_ex(title)
        if number is None:
            return None
        chapter = kind == "chapter"
        item = self.by_number.get((chapter, number))
        if item is None and not chapter:
            item = self.orphans.setdefault(number, SeriesItem(number, title=title))
        self.by_key[volume] = item
        return item


def _read_enough(pages, item) -> bool:
    return pages >= (READ_SHARE * item.total if item.total else UNKNOWN_READ_PAGES)


def build_series_report(log, holdings: SeriesHoldings, today: _dt.date, resolve=None,
                        library_pace=None, owner=None) -> SeriesReport:
    """Rapport d'une serie. `log` : le journal de lecture ; `resolve` : voir
    stats.top_series (rang de la serie) ; `library_pace` : rythme moyen,
    repli de l'estimation ; `owner` : voir collect_rows."""
    rows = collect_rows(log, holdings, owner)
    slots = _Slots(holdings.items)
    acc: dict = {}        # element -> [pages, secondes, seances, premiere fin, d'une traite]
    days: dict = {}       # jour -> [secondes, pages, seances, lecture ?, lignes, fins, debuts]
    first_pages: dict = {}   # element -> premier jour avec des pages
    devices: dict = {}
    real_pages = real_seconds = 0.0
    for day, device, volume, pages, seconds, sessions, finished, title in rows:
        item = slots.find(volume, title)
        real = pages >= GLANCE_PAGES
        d = days.setdefault(day, [0.0, 0, 0, False, 0, [], set()])
        d[0] += seconds
        d[1] += pages
        d[4] += 1
        if real:
            d[2] += sessions
            d[3] = True
            real_pages += pages
            real_seconds += seconds
        devices[device] = devices.get(device, 0.0) + seconds
        if item is None:
            continue
        a = acc.setdefault(item, [0, 0.0, 0, None, False])
        a[0] += pages
        a[1] += seconds
        if real:
            a[2] += sessions
        if finished and a[3] is None:
            a[3] = _dt.date.fromisoformat(day)
            d[5].append(item)
        if sessions == 1 and _read_enough(pages, item):
            a[4] = True
        if pages and item not in first_pages:
            first_pages[item] = day
            d[6].add(item)

    items = list(holdings.items) + [i for i in slots.orphans.values() if acc[i][3] is not None]
    volumes = []
    for item in sorted(items, key=item_order):
        if item.volume is None:     # tome supprime, termine dans le journal
            item = SeriesItem(item.number, item.unit, None, FINISHED, title=item.title)
            pages, seconds, sessions, done, sitting = acc[slots.orphans[item.number]]
        else:
            pages, seconds, sessions, done, sitting = acc.get(item, (0, 0.0, 0, None, False))
        here = item.status == FINISHED and seconds > 0 and _read_enough(pages, item)
        volumes.append(VolumeStat(item, int(pages), float(seconds), sessions,
                                  done if item.status == FINISHED else None, here,
                                  here and sitting))

    journal: list = []
    best: Optional[DayEntry] = None
    for day in sorted(days, reverse=True):
        seconds, pages, sessions, real, count, done, started = days[day]
        date = _dt.date.fromisoformat(day)
        if not real:
            prev = journal[-1] if journal else None
            if isinstance(prev, GlanceRun):
                journal[-1] = GlanceRun(date, prev.last, prev.count + count, prev.seconds + seconds)
            else:
                journal.append(GlanceRun(date, date, count, seconds))
            continue
        entry = DayEntry(date, seconds, pages, sessions,
                         tuple(sorted(done, key=item_order)),
                         tuple(sorted((i for i in started if i not in done), key=item_order)))
        journal.append(entry)
        if best is None or seconds > best.seconds:
            best = entry
    reading = [e.day for e in journal if isinstance(e, DayEntry)]
    any_day = sorted(days)
    first = min(reading) if reading else (_dt.date.fromisoformat(any_day[0]) if any_day else None)
    last = max(reading) if reading else (_dt.date.fromisoformat(any_day[-1]) if any_day else None)
    sessions = sum(e.sessions for e in journal if isinstance(e, DayEntry))

    pace = (real_seconds / real_pages
            if real_pages >= stats.SERIES_PACE_MIN_PAGES and real_seconds > 0 else None)
    rate = pace or library_pace or 0.0
    remaining_pages = unknown = left = 0
    for item in holdings.items:
        if item.status == FINISHED:
            continue
        left += 1
        if item.total:
            remaining_pages += max(0, item.total - item.page)
        else:
            unknown += 1
    remaining = remaining_pages * rate
    per_day = real_seconds / len(reading) if reading else 0.0

    rank, share = None, 0.0
    if resolve is not None and first is not None:
        ranking = stats.top_series(log.volumes(log.first_day() or first, today), resolve,
                                   n=1 << 30)
        for i, s in enumerate(ranking):
            if s.key == holdings.key:
                rank, share = i + 1, s.share
                break

    return SeriesReport(
        holdings=holdings, seconds=sum(d[0] for d in days.values()),
        pages=sum(d[1] for d in days.values()), active_days=len(reading), sessions=sessions,
        first_day=first, last_day=last, volumes=volumes, journal=journal,
        pace=pace, library_pace=library_pace,
        remaining_seconds=remaining, remaining_items=left, unknown_pages=unknown,
        remaining_days=remaining / per_day if remaining and per_day else None,
        rank=rank, share=share, best_day=best,
        session_seconds=real_seconds / sessions if sessions else 0.0,
        session_pages=real_pages / sessions if sessions else 0.0,
        devices=sorted(((name, s) for name, s in devices.items() if s > 0),
                       key=lambda d: (-d[1], d[0])))
