"""Statistiques de lecture : logique pure (aucune dependance Qt, testee
isolement).

Le journal (stats.json, gere par storage.Store) est organise par appareil,
pour que l'import d'une sauvegarde venant d'un autre PC fusionne sans double
compte (voir backup.py) :

    {"devices": {
        <id appareil>: {
            "name": "PC-SALON", "updated": <epoch>,
            "days": {"2026-09-27": {<empreinte du tome>: {
                "pages": 42, "seconds": 1260.0, "finished": 1,
                "title": "Berserk - Tome 3", "series": "Berserk"}}}}}}

Chaque appareil n'ecrit que dans sa propre section ; les vues ci-dessous
additionnent toutes les sections.
"""

import datetime as _dt


def day_key(date: _dt.date) -> str:
    return date.isoformat()


def add_session(device: dict, date: _dt.date, key: str, pages: int, seconds: float,
                finished: bool, title: str, series: str):
    """Ajoute une session de lecture au journal d'un appareil (en place)."""
    day = device.setdefault("days", {}).setdefault(day_key(date), {})
    rec = day.setdefault(key, {"pages": 0, "seconds": 0.0, "finished": 0})
    rec["pages"] = int(rec.get("pages", 0)) + max(0, int(pages))
    rec["seconds"] = round(float(rec.get("seconds", 0.0)) + max(0.0, float(seconds)), 1)
    if finished:
        rec["finished"] = int(rec.get("finished", 0)) + 1
    rec["title"] = title
    rec["series"] = series


def merged_days(stats: dict) -> dict:
    """{jour: {empreinte: enregistrement}} additionne sur tous les appareils."""
    out = {}
    for dev in (stats or {}).get("devices", {}).values():
        for day, recs in dev.get("days", {}).items():
            target = out.setdefault(day, {})
            for key, rec in recs.items():
                t = target.setdefault(key, {"pages": 0, "seconds": 0.0, "finished": 0,
                                            "title": rec.get("title", ""),
                                            "series": rec.get("series", "")})
                t["pages"] += int(rec.get("pages", 0))
                t["seconds"] += float(rec.get("seconds", 0.0))
                t["finished"] += int(rec.get("finished", 0))
    return out


def daily_totals(days: dict) -> dict:
    """{jour: (pages, secondes)}."""
    return {day: (sum(r["pages"] for r in recs.values()),
                  sum(r["seconds"] for r in recs.values()))
            for day, recs in days.items()}


def last_n_days(daily: dict, today: _dt.date, n: int = 30):
    """[(date, pages, secondes)] des n derniers jours, aujourd'hui compris,
    du plus ancien au plus recent (jours sans lecture a zero)."""
    out = []
    for i in range(n - 1, -1, -1):
        d = today - _dt.timedelta(days=i)
        pages, seconds = daily.get(day_key(d), (0, 0.0))
        out.append((d, pages, seconds))
    return out


def streak(daily: dict, today: _dt.date) -> int:
    """Jours consecutifs de lecture se terminant aujourd'hui - ou hier, pour
    que la serie ne tombe pas a zero le matin avant d'avoir lu."""
    def read_on(d):
        return daily.get(day_key(d), (0, 0))[0] > 0
    d = today if read_on(today) else today - _dt.timedelta(days=1)
    n = 0
    while read_on(d):
        n += 1
        d -= _dt.timedelta(days=1)
    return n


def top_series(days: dict, since: _dt.date = None, n: int = 5):
    """[(serie, secondes, pages)] les plus lues (temps de lecture), depuis
    `since` si fourni."""
    acc = {}
    for day, recs in days.items():
        if since is not None and day < day_key(since):
            continue
        for rec in recs.values():
            name = rec.get("series") or rec.get("title") or "?"
            s, p = acc.get(name, (0.0, 0))
            acc[name] = (s + rec["seconds"], p + rec["pages"])
    ranked = sorted(acc.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0].casefold()))
    return [(name, s, p) for name, (s, p) in ranked[:n] if s > 0 or p > 0]


def finished_per_month(progress: dict, today: _dt.date, months: int = 12):
    """[(date du 1er du mois, nombre)] des tomes termines par mois, sur les
    `months` derniers mois. S'appuie sur la progression (drapeau « termine »
    et date de derniere lecture) : disponible des l'installation, meme sans
    historique de sessions."""
    firsts = []
    y, m = today.year, today.month
    for _ in range(months):
        firsts.append(_dt.date(y, m, 1))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    firsts.reverse()
    counts = {f: 0 for f in firsts}
    for entry in (progress or {}).values():
        if not isinstance(entry, dict) or not entry.get("finished"):
            continue
        ts = entry.get("ts")
        if not ts:
            continue
        d = _dt.date.fromtimestamp(ts)
        f = _dt.date(d.year, d.month, 1)
        if f in counts:
            counts[f] += 1
    return [(f, counts[f]) for f in firsts]


def finished_total(progress: dict, year: int = None) -> int:
    n = 0
    for entry in (progress or {}).values():
        if not isinstance(entry, dict) or not entry.get("finished"):
            continue
        if year is not None:
            ts = entry.get("ts")
            if not ts or _dt.date.fromtimestamp(ts).year != year:
                continue
        n += 1
    return n


def fmt_duration(seconds: float) -> str:
    """Duree lisible : « 45 min », « 3 h 05 », « moins d'une minute »."""
    minutes = int(round(seconds / 60.0))
    if seconds > 0 and minutes == 0:
        return "moins d'une minute"
    if minutes < 60:
        return f"{minutes} min"
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
