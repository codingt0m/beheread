"""Statistiques de lecture : logique pure (aucune dependance Qt, testee
isolement).

Le journal de lecture est une table SQLite (voir infra/reading_log.py) :
une ligne par jour, appareil et tome, avec les pages lues, le temps actif,
le nombre de seances et les fins de tome. Ce module ne fait aucune requete :
il definit les periodes, complete et compare les agregats que le journal
renvoie, et les assemble en un rapport (build_report) que la fenetre de
statistiques n'a plus qu'a dessiner.

Tous les indicateurs d'un rapport portent sur la MEME periode, et chacun
est accompagne de sa valeur sur la periode precedente de meme duree.

Format d'echange (sauvegarde, voir backup.py), une section par appareil
pour que l'import d'un autre PC fusionne sans double compte :

    {"devices": {
        <id appareil>: {
            "name": "PC-SALON", "updated": <epoch>, "rules": 2,
            "days": {"2026-09-27": {<empreinte du tome>: {
                "pages": 42, "seconds": 1260.0, "sessions": 2, "finished": 1,
                "title": "Berserk - Tome 3", "series": "Berserk"}}}}}}

« rules » est la version des regles de mesure (voir reading_session.py).
Une section sans ce champ vient d'une version qui comptait toute page
tournee, meme feuilletee : ses pages sont ramenees a ce que son temps de
lecture rend possible (journal_rows).
"""

import datetime as _dt
from dataclasses import dataclass
from typing import Optional

from beheread.core.reading_session import MIN_DWELL
from beheread.core.series import normalize_name

JOURNAL_RULES = 2

PERIODS = (("7d", "7 jours"), ("30d", "30 jours"), ("12m", "12 mois"), ("all", "Tout"))
DEFAULT_PERIOD = "30d"
# « Tout » : barres par jour tant que l'historique est court, par mois ensuite
ALL_DAILY_MAX_DAYS = 62
# calendrier de regularite : 53 semaines au plus (les plus recentes de la periode)
CALENDAR_MAX_DAYS = 53 * 7
HEAT_LEVELS = 4          # nuances du calendrier, en plus de « aucune lecture »
FINISHED_LIST_MAX = 12   # derniers tomes termines proposes a l'affichage

_DAY = _dt.timedelta(days=1)


def day_key(date: _dt.date) -> str:
    return date.isoformat()


# ---------------------------------------------------------------- periodes

@dataclass(frozen=True)
class Period:
    key: str
    start: _dt.date
    end: _dt.date
    grain: str                  # pas des graphiques : "day" ou "month"
    previous: Optional[tuple]   # (debut, fin) de la periode de comparaison, ou None
    label: str                  # « 30 derniers jours »
    previous_label: str         # « 30 jours précédents »

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _add_months(first: _dt.date, months: int) -> _dt.date:
    """Premier jour du mois situe `months` mois apres (ou avant) `first`."""
    index = first.year * 12 + first.month - 1 + months
    return _dt.date(index // 12, index % 12 + 1, 1)


def _year_before(date: _dt.date) -> _dt.date:
    try:
        return date.replace(year=date.year - 1)
    except ValueError:   # 29 fevrier
        return date.replace(year=date.year - 1, day=28)


def period(key: str, today: _dt.date, first_day: Optional[_dt.date] = None) -> Period:
    """Periode d'analyse se terminant aujourd'hui. `first_day` : premier jour
    du journal, borne de la periode « Tout »."""
    if key == "all":
        start = min(first_day or today, today)
        grain = "day" if (today - start).days < ALL_DAILY_MAX_DAYS else "month"
        label = f"depuis le {start.strftime('%d/%m/%Y')}" if first_day else "tout l'historique"
        return Period("all", start, today, grain, None, label, "")
    if key == "12m":
        start = _add_months(today.replace(day=1), -11)
        # meme decoupage un an plus tot : le mois en cours, incomplet, est
        # compare au meme mois arrete au meme jour
        previous = (_add_months(start, -12), _year_before(today))
        return Period("12m", start, today, "month", previous, "12 derniers mois",
                      "12 mois précédents")
    n = 7 if key == "7d" else 30
    start = today - (n - 1) * _DAY
    return Period("7d" if n == 7 else "30d", start, today, "day",
                  (start - n * _DAY, start - _DAY), f"{n} derniers jours",
                  f"{n} jours précédents")


# ---------------------------------------------------------------- agregats

@dataclass(frozen=True)
class Totals:
    pages: int = 0
    seconds: float = 0.0
    sessions: int = 0
    finished: int = 0       # tomes lus jusqu'a la derniere page
    active_days: int = 0    # jours avec au moins une page lue
    volumes: int = 0        # tomes differents lus

    @property
    def empty(self) -> bool:
        return not (self.pages or self.seconds or self.finished)


@dataclass(frozen=True)
class Bucket:
    """Une barre des graphiques : un jour ou un mois (`start` : son premier jour)."""
    start: _dt.date
    pages: int = 0
    seconds: float = 0.0
    finished: int = 0


def bucket_key(date: _dt.date, grain: str) -> str:
    return date.isoformat()[:7] if grain == "month" else date.isoformat()


def _fill(start: _dt.date, end: _dt.date, grain: str, rows) -> list:
    found = {key: (pages, seconds, finished) for key, pages, seconds, finished in rows}
    out = []
    if grain == "month":
        d, last = start.replace(day=1), end.replace(day=1)
        step = lambda x: _add_months(x, 1)   # noqa: E731
    else:
        d, last = start, end
        step = lambda x: x + _DAY            # noqa: E731
    while d <= last:
        pages, seconds, finished = found.get(bucket_key(d, grain), (0, 0.0, 0))
        out.append(Bucket(d, int(pages), float(seconds), int(finished)))
        d = step(d)
    return out


def fill_buckets(p: Period, rows) -> list:
    """Barres de la periode, de la plus ancienne a la plus recente, a partir
    des lignes agregees [(cle, pages, secondes, fins)] du journal ; les jours
    ou mois sans lecture sont a zero."""
    return _fill(p.start, p.end, p.grain, rows)


# ---------------------------------------------------------------- calendrier de regularite

def calendar_start(p: Period) -> _dt.date:
    """Premier jour du calendrier : celui de la periode, ou le debut des 53
    dernieres semaines si elle est plus longue."""
    return max(p.start, p.end - (CALENDAR_MAX_DAYS - 1) * _DAY)


def calendar_weeks(days) -> list:
    """Semaines (lundi -> dimanche) couvrant les jours donnes (Bucket, dans
    l'ordre) : listes de 7 cases, None pour les jours hors periode."""
    weeks = []
    for b in days:
        weekday = b.start.weekday()
        if not weeks or weekday == 0:
            weeks.append([None] * 7)
        weeks[-1][weekday] = b
    return weeks


def heat_thresholds(values, levels: int = HEAT_LEVELS) -> list:
    """Seuils des nuances du calendrier : les quantiles des valeurs non
    nulles, pour qu'une journee exceptionnelle n'ecrase pas toutes les
    autres dans la nuance la plus claire."""
    positive = sorted(v for v in values if v > 0)
    if not positive:
        return []
    n = len(positive)
    return [positive[min(n - 1, k * n // levels)] for k in range(1, levels)]


def heat_level(value, thresholds) -> int:
    """Nuance d'une journee : 0 sans lecture, puis 1 (peu) a HEAT_LEVELS (beaucoup)."""
    if value <= 0:
        return 0
    return 1 + sum(1 for t in thresholds if value >= t)


def streaks(days, today: _dt.date) -> tuple:
    """(serie en cours, record) en jours consecutifs de lecture, d'apres les
    jours « AAAA-MM-JJ » ou au moins une page a ete lue. La serie en cours se
    termine aujourd'hui - ou hier, pour qu'elle ne tombe pas a zero le matin
    avant d'avoir lu."""
    dates = set()
    for d in days:
        try:
            dates.add(_dt.date.fromisoformat(d))
        except (TypeError, ValueError):
            continue
    best = run = 0
    prev = None
    for d in sorted(dates):
        run = run + 1 if prev is not None and d - prev == _DAY else 1
        best = max(best, run)
        prev = d
    d = today if today in dates else today - _DAY
    current = 0
    while d in dates:
        current += 1
        d -= _DAY
    return current, best


@dataclass(frozen=True)
class SeriesRank:
    name: str
    seconds: float
    pages: int
    finished: int
    share: float    # part du temps de lecture de la periode (0 a 1)


def top_series(volume_rows, resolve=None, n: int = 6) -> list:
    """Series les plus lues (temps de lecture, puis pages), a partir des
    lignes par tome [(tome, titre, serie, pages, secondes, fins)] du journal.

    `resolve(tome)` renvoie (cle de serie, nom affiche) pour un tome present
    dans la bibliotheque : le classement suit alors les regroupements et les
    noms ACTUELS, meme si la serie a ete renommee ou regroupee depuis. Pour
    un tome inconnu (fichier supprime, autre PC), on se rabat sur le nom de
    serie note au moment de la lecture."""
    groups = {}
    for volume, title, series, pages, seconds, finished in volume_rows:
        if not (pages or seconds):
            continue
        key_name = resolve(volume) if resolve is not None else None
        if key_name is None:
            label = series or title or "?"
            key_name = (normalize_name(label) or label, label)
        g = groups.setdefault(key_name[0], [key_name[1], 0.0, 0, 0])
        g[1] += seconds
        g[2] += pages
        g[3] += finished
    total_seconds = sum(g[1] for g in groups.values())
    total_pages = sum(g[2] for g in groups.values())
    ranked = sorted(groups.values(), key=lambda g: (-g[1], -g[2], g[0].casefold()))
    return [SeriesRank(name, seconds, pages, finished,
                       seconds / total_seconds if total_seconds
                       else (pages / total_pages if total_pages else 0.0))
            for name, seconds, pages, finished in ranked[:n]]


# ---------------------------------------------------------------- rapport

@dataclass(frozen=True)
class Report:
    period: Period
    totals: Totals
    previous: Optional[Totals]      # None : pas de periode de comparaison
    buckets: list
    streak: int
    best_streak: int
    series: list
    first_day: Optional[_dt.date]       # premier jour du journal, None s'il est vide
    first_session: Optional[_dt.date]   # premier jour ou pages et temps sont mesures
    calendar: list                      # un Bucket par jour (voir calendar_start)
    finished_volumes: list              # dernieres fins de tome [(date, tome, titre, serie)]


def build_report(log, key: str, today: _dt.date, resolve=None, top: int = 6) -> Report:
    """Rapport complet d'une periode. `log` : le journal de lecture
    (infra.reading_log.ReadingLog) ; chaque indicateur est une requete
    agregee bornee a la periode."""
    first = log.first_day()
    p = period(key, today, first)
    current, best = streaks(log.active_days(), today)
    return Report(
        period=p,
        totals=log.totals(p.start, p.end),
        previous=log.totals(*p.previous) if p.previous else None,
        buckets=fill_buckets(p, log.buckets(p.start, p.end, p.grain)),
        streak=current, best_streak=best,
        series=top_series(log.volumes(p.start, p.end), resolve, top),
        first_day=first, first_session=log.first_day(sessions_only=True),
        calendar=_fill(calendar_start(p), p.end, "day",
                       log.buckets(calendar_start(p), p.end, "day")),
        finished_volumes=[(_dt.date.fromisoformat(day), volume, title, series)
                          for day, volume, title, series
                          in log.finished(p.start, p.end, FINISHED_LIST_MAX)])


# ---------------------------------------------------------------- format d'echange

def _count(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _seconds(value) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def journal_rows(device: str, section):
    """Lignes du journal (jour, appareil, tome, pages, secondes, seances,
    fins, titre, serie) d'une section d'appareil au format d'echange. Tolere
    une section abimee (enregistrements illisibles ignores)."""
    if not isinstance(section, dict) or not isinstance(section.get("days"), dict):
        return
    legacy = _count(section.get("rules", 1)) < JOURNAL_RULES
    for day, records in section["days"].items():
        try:
            _dt.date.fromisoformat(day)
        except (TypeError, ValueError):
            continue
        if not isinstance(records, dict):
            continue
        for volume, rec in records.items():
            if not isinstance(volume, str) or not isinstance(rec, dict):
                continue
            pages, seconds = _count(rec.get("pages")), _seconds(rec.get("seconds"))
            finished = _count(rec.get("finished"))
            if legacy:
                # anciennes regles : toute page tournee comptait. On ne garde
                # que ce que le temps de lecture rend possible.
                pages = min(pages, int(seconds / MIN_DWELL))
            if not (pages or seconds or finished):
                continue
            sessions = _count(rec.get("sessions", 1 if (pages or seconds) else 0))
            yield (day, device, volume, pages, round(seconds, 1), sessions, finished,
                   str(rec.get("title") or ""), str(rec.get("series") or ""))


def journal_section(name: str, updated: float, rows) -> dict:
    """Section d'appareil au format d'echange, a partir de ses lignes
    [(jour, tome, pages, secondes, seances, fins, titre, serie)]."""
    days = {}
    for day, volume, pages, seconds, sessions, finished, title, series in rows:
        days.setdefault(day, {})[volume] = {
            "pages": pages, "seconds": seconds, "sessions": sessions, "finished": finished,
            "title": title, "series": series}
    return {"name": name, "updated": updated, "rules": JOURNAL_RULES, "days": days}


def finished_before_journal(progress: dict, before: _dt.date) -> list:
    """[(jour, empreinte)] des tomes termines avant le `before`, premier jour
    du journal : faute de mieux, leur fin est datee de leur derniere lecture
    (horodatage de la progression). A partir du premier jour du journal,
    seules les fins qu'il a enregistrees comptent : cet horodatage bouge a
    chaque reouverture d'un tome, et « Marquer comme lu » n'est pas une
    lecture."""
    out = []
    for key, entry in (progress or {}).items():
        if not isinstance(entry, dict) or not entry.get("finished"):
            continue
        try:
            day = _dt.date.fromtimestamp(float(entry.get("ts") or 0))
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if entry.get("ts") and day < before:
            out.append((day.isoformat(), key))
    return out


# ---------------------------------------------------------------- mise en forme

def fmt_duration(seconds: float, compact: bool = False) -> str:
    """Duree lisible : « 45 min », « 3 h 05 », « moins d'une minute ».
    `compact` (graduations, listes) : « 3 h » plutot que « 3 h 00 », et
    « 28 s » plutot que « moins d'une minute »."""
    minutes = int(round(seconds / 60.0))
    if seconds > 0 and minutes == 0:
        return f"{max(1, round(seconds))} s" if compact else "moins d'une minute"
    if minutes < 60:
        return f"{minutes} min"
    if compact and minutes % 60 == 0:
        return f"{minutes // 60} h"
    return f"{minutes // 60} h {minutes % 60:02d}"


def nice_ticks(max_value: float, count: int = 4):
    """Graduations « rondes » de 0 a au moins max_value (1, 2, 5 x 10^n)."""
    if max_value <= 0:
        return [0, 1]
    raw = max_value / count
    mag = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 1
    for mult in (1, 2, 5, 10):
        step = mult * mag
        if step >= raw:
            break
    step = max(1, int(step))
    top = step * -(-int(max_value) // step)
    return list(range(0, top + 1, step))


# pas « ronds » d'un axe de durees, en secondes : 1 min ... 1 jour
_TIME_STEPS = (60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400)


def time_ticks(max_seconds: float, count: int = 4):
    """Graduations d'un axe de durees (en secondes), de 0 a au moins
    max_seconds : pas de 1, 2, 5, 10, 15, 30 min, 1, 2, 3, 6, 12 h, puis en jours."""
    if max_seconds <= 0:
        return [0, 60]
    step = next((s for s in _TIME_STEPS if s * count >= max_seconds), None)
    if step is None:
        step = 86400 * nice_ticks(max_seconds / 86400, count)[1]
    top = step * -(-int(max_seconds) // step)
    return list(range(0, max(top, step) + 1, step))
