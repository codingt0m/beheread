"""Vue « statistiques d'une serie », dans la fenetre Statistiques (voir
stats_view.py, qui l'affiche a la place de la vue generale et lui prete sa
feuille de style).

Hierarchie, de haut en bas (maquette validee le 2026-10-24) :

1. les chiffres cles : temps passe dans la serie (chiffre principal, avec
   la tendance des douze derniers mois), tomes lus sur possedes, rythme de
   la serie compare au rythme moyen, reste a lire et fin estimee ;
2. l'etagere : une case par tome, la forme d'une serie (les trous, le tome
   en cours, ce qui reste) ;
3. la progression (escalier cumule + projection), le temps de lecture de
   chaque tome (avec la mediane) et quelques reperes.

Tout l'historique de la serie, sans periode a choisir : elle se lit sur une
duree finie. Les calculs sont dans core/series_stats.py ; ce module ne fait
que dessiner un SeriesReport.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from beheread.core import series_stats as ss
from beheread.core import stats, units
from beheread.i18n import N_, tr, trn
from beheread.ui.charts import (
    BarChart,
    ChartCard,
    Meter,
    PaceScale,
    Shelf,
    Sparkline,
    StatTile,
    StepChart,
    _fmt_int,
    fmt_day,
    fmt_estimate,
    fmt_pace,
    month_name,
)

# libelles traduits a l'affichage (tr)
_STATUS = {ss.FINISHED: N_("Terminé"), ss.READING: N_("En cours"), ss.UNREAD: N_("Non lu"),
           ss.MISSING: N_("Non possédé")}


def _status(item) -> str:
    return tr(_STATUS.get(item.status, ""))


def item_name(item) -> str:
    """« Tome 12 », « Chapitre 211 », ou le titre d'un fichier sans numero."""
    if item.number is None:
        return item.title or "?"
    number = units.fmt_number(item.number)
    return tr("Chapitre {n}", n=number) if units.is_chapter(item.unit) else tr("Tome {n}", n=number)


def _content(items) -> str:
    """Ce que compte la serie : "volumes", "chapters" ou "mixed"."""
    chapters = {units.is_chapter(i.unit) for i in items}
    return "chapters" if chapters == {True} else "volumes" if chapters == {False} else "mixed"


# (titre de la tuile, singulier, pluriel) selon le contenu de la serie
_COUNTED = {"volumes": (N_("Tomes lus"), N_("{n} tome"), N_("{n} tomes")),
            "chapters": (N_("Chapitres lus"), N_("{n} chapitre"), N_("{n} chapitres")),
            "mixed": (N_("Lus"), N_("{n} titre"), N_("{n} titres"))}


class SeriesStatsView(QWidget):
    def __init__(self, colors, data_colors, parent=None):
        super().__init__(parent)
        self.c, self.dc = colors, data_colors
        self.report = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # --- chiffres cles
        self.spark = Sparkline(data_colors["activity"], colors)
        self.read_meter = Meter(data_colors["finished"])
        self.pace_scale = PaceScale(data_colors["activity"], colors)
        self.tiles = [StatTile(tr("Temps passé dans la série"), self.spark, hero=True),
                      StatTile(tr("Tomes lus"), self.read_meter),
                      StatTile(tr("Rythme"), self.pace_scale),
                      StatTile(tr("Reste à lire"))]
        tiles = QWidget()
        grid = QGridLayout(tiles)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.addWidget(self.tiles[0], 0, 0, 1, 2)
        for i, tile in enumerate(self.tiles[1:]):
            grid.addWidget(tile, 0, 2 + i)
        for col in range(5):
            grid.setColumnStretch(col, 1)
        v.addWidget(tiles)

        # --- etagere
        self.shelf = Shelf({ss.FINISHED: data_colors["finished"], ss.READING: data_colors["reading"],
                            ss.UNREAD: data_colors["unread"]}, colors)
        self.shelf_card = ChartCard(tr("La série, tome par tome"), self.shelf)
        v.addWidget(self.shelf_card)

        # --- progression, temps par tome, reperes
        self.progress = StepChart(data_colors["finished"], colors,
                                  tr("Aucun tome terminé dans le lecteur pour l'instant."))
        self.progress_card = ChartCard(tr("Progression"), self.progress,
                                       [tr("Date"), tr("Terminé"), tr("Cumul")])
        self.bars = BarChart(data_colors["activity"], colors, ticks=stats.time_ticks,
                             value_fmt=lambda s: stats.fmt_duration(s, compact=True),
                             empty_text=tr("Aucun tome terminé dans le lecteur pour l'instant."),
                             height=170)
        self.bars_card = ChartCard(tr("Temps de lecture par tome"), self.bars,
                                   [tr("Tome"), tr("Temps"), tr("Pages"), tr("s / page")])
        self.facts = QWidget()
        self.facts_grid = QGridLayout(self.facts)
        self.facts_grid.setContentsMargins(0, 4, 0, 0)
        self.facts_grid.setHorizontalSpacing(14)
        self.facts_grid.setVerticalSpacing(9)
        self.facts_grid.setColumnStretch(1, 1)
        self.facts_card = ChartCard(tr("Repères"), self.facts)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self.progress_card, 5)
        row.addWidget(self.bars_card, 5)
        row.addWidget(self.facts_card, 4)
        v.addLayout(row, 1)

    # ------------------------------------------------------------ mise a jour
    def caption(self) -> str:
        """Ligne sous le titre : auteur et etendue de la lecture."""
        r = self.report
        parts = [r.holdings.author] if r.holdings.author else []
        if r.first_day is not None:
            parts.append(tr("lue du {start} au {end}", start=fmt_day(r.first_day),
                            end=fmt_day(r.last_day)))
        else:
            parts.append(tr("pas encore lue dans le lecteur"))
        return " · ".join(parts)

    def set_report(self, report, today):
        self.report, self.today = report, today
        self._refresh_tiles()
        self._refresh_shelf()
        self._refresh_progress()
        self._refresh_bars()
        self._refresh_facts()

    def _refresh_tiles(self):
        r, t = self.report, self.report.totals
        hero, read, pace, left = self.tiles
        title, one, many = _COUNTED[_content(r.holdings.owned or r.holdings.items)]
        details = [trn(t.pages, "{n} page", "{n} pages"),
                   trn(t.sessions, "{n} séance", "{n} séances")]
        hero.set_content(stats.fmt_duration(t.seconds), "", " · ".join(details),
                         tr("Temps de lecture par mois, sur les 12 derniers mois"))
        self.spark.set_values(b.seconds for b in r.months)

        read.set_label(tr(title))
        sub = [tr("{n} %", n=round(100 * r.finished / r.owned))] if r.owned else []
        if r.holdings.published:
            sub.append(trn(r.holdings.published, "{n} tome paru", "{n} tomes parus"))
        read.set_content(tr("{n} sur {total}", n=_fmt_int(r.finished), total=_fmt_int(r.owned)),
                         "", " · ".join(sub))
        self.read_meter.set_ratio(r.finished / r.owned if r.owned else 0)

        self.pace_scale.set_paces(r.pace, r.library_pace)
        if r.pace and r.library_pace:
            diff = round(100 * (r.pace / r.library_pace - 1))
            text = (tr("comme votre moyenne") if not diff
                    else tr("{diff} % par rapport à votre moyenne ({pace}, trait gris)",
                            diff=f"{diff:+d}", pace=fmt_pace(r.library_pace)))
            pace.set_content(fmt_pace(r.pace), "", text,
                             tr("Plus le point est à droite, plus la série se lit lentement."))
        else:
            pace.set_content("–", "", tr("Pas encore assez de pages lues dans la série pour "
                                         "mesurer son rythme."))

        if not r.remaining_items:
            text = tr("Tout ce que vous possédez est lu.")
            if r.holdings.published and r.holdings.published > r.owned:
                text += " " + trn(r.holdings.published - r.owned, "{n} tome paru non possédé.",
                                  "{n} tomes parus non possédés.")
            left.set_content(tr("Rien"), "", text)
            return
        lines = [trn(r.remaining_items, one, many)
                 + (" " + tr("au rythme de la série") if r.pace else "")]
        if r.projected_end is not None:
            lines.append(tr("Fin estimée : {month} {year}",
                            month=month_name(r.projected_end.month), year=r.projected_end.year))
        tip = trn(r.recent_finished,
                  "Fin estimée d'après {n} fin de lecture dans les 90 derniers jours.",
                  "Fin estimée d'après {n} fins de lecture dans les 90 derniers jours.") \
            if r.projected_end else ""
        if r.unknown_pages:
            tip = "\n".join(p for p in (tip, trn(r.unknown_pages,
                                                 "Hors {n} titre au nombre de pages inconnu.",
                                                 "Hors {n} titres au nombre de pages inconnu."))
                            if p)
        value = "≈ " + fmt_estimate(r.remaining_seconds) if r.remaining_seconds else "–"
        left.set_content(value, "", "\n".join(lines), tip)

    def _refresh_shelf(self):
        r = self.report
        items, counts = [], {}
        for v in r.volumes:
            item = v.item
            counts[item.status] = counts.get(item.status, 0) + 1
            tip = f"{item_name(item)} · {_status(item)}"
            if item.status == ss.FINISHED and v.seconds:
                tip += "\n" + stats.fmt_duration(v.seconds) + " · " + trn(v.pages, "{n} page", "{n} pages")
            if v.finished_on:
                tip += "\n" + tr("terminé le {day}", day=fmt_day(v.finished_on))
            if item.status == ss.READING and item.total:
                tip += " · " + tr("page {page} / {total}", page=item.page + 1, total=item.total)
            if item.status == ss.UNREAD and item.total and (r.pace or r.library_pace):
                tip += "\n≈ " + stats.fmt_duration(item.total * (r.pace or r.library_pace))
            progress = item.page / item.total if item.total else 0.0
            label = units.fmt_number(item.number) if item.number is not None else "·"
            items.append((label, item.status, progress, tip))
        labels = ((ss.FINISHED, "{n} terminé", "{n} terminés"), (ss.READING, "{n} en cours", "{n} en cours"),
                  (ss.UNREAD, "{n} non lu", "{n} non lus"),
                  (ss.MISSING, "{n} non possédé", "{n} non possédés"))
        self.shelf.set_items(items, [(trn(counts[s], one, many), s)
                                     for s, one, many in labels if counts.get(s)])
        parts = []
        if r.holdings.published:
            parts.append(trn(r.holdings.published, "{n} tome paru", "{n} tomes parus"))
        parts.append(trn(r.owned, "{n} possédé", "{n} possédés"))
        self.shelf_card.set_subtitle(" · ".join(parts))

    def _refresh_progress(self):
        r = self.report
        points = [(day, count, tr("{name} terminé · {day}", name=item_name(v.item), day=fmt_day(day))
                   + "\n" + trn(count, "{n} lu à cette date", "{n} lus à cette date"))
                  for day, count, v in r.progression]
        projection = None
        if r.projected_end is not None:
            target = (r.progression[-1][1] if r.progression else r.base) + r.remaining_items
            projection = (r.projected_end, target,
                          tr("Fin estimée : {month} {year}", month=month_name(r.projected_end.month),
                             year=r.projected_end.year) + "\n"
                          + trn(r.recent_finished,
                                "au rythme des 90 derniers jours ({n} fin de lecture)",
                                "au rythme des 90 derniers jours ({n} fins de lecture)"))
        refs = [(r.owned, trn(r.owned, "{n} possédé", "{n} possédés"))]
        if r.holdings.published and r.holdings.published != r.owned:
            refs.append((r.holdings.published, trn(r.holdings.published, "{n} paru", "{n} parus")))
        self.progress.set_data(r.first_day, r.base, points, self.today, projection, refs)
        subtitle = tr("Terminés, cumulés")
        if r.base:
            subtitle += " · " + trn(r.base, "dont {n} avant le journal ou marqué lu",
                                    "dont {n} avant le journal ou marqués lus")
        self.progress_card.set_subtitle(subtitle)
        self.progress_card.set_table([(fmt_day(day), item_name(v.item), _fmt_int(count))
                                      for day, count, v in reversed(r.progression)])

    def _refresh_bars(self):
        r = self.report
        timed = [i for i, v in enumerate(r.volumes) if v.item.status == ss.FINISHED and v.seconds]
        span = r.volumes[timed[0]:timed[-1] + 1] if timed else []
        bars, rows = [], []
        for v in span:
            label = units.fmt_number(v.item.number) if v.item.number is not None else ""
            if v.item.status == ss.FINISHED and v.seconds:
                pace = v.seconds / v.pages if v.pages else 0
                tip = (f"{stats.fmt_duration(v.seconds)}\n{item_name(v.item)} · "
                       + trn(v.pages, "{n} page", "{n} pages")
                       + (" · " + fmt_pace(pace) if pace else ""))
                bars.append((label, v.seconds, tip))
                rows.append((item_name(v.item), stats.fmt_duration(v.seconds), _fmt_int(v.pages),
                             f"{pace:.0f}" if pace else ""))
            else:
                bars.append((label, 0, f"{item_name(v.item)} · {_status(v.item)}"))
        seconds = sorted(r.volumes[i].seconds for i in timed)
        median = seconds[len(seconds) // 2] if seconds else 0
        self.bars.set_bars(bars, (median, tr("médiane {duration}",
                                             duration=stats.fmt_duration(median)))
                           if len(seconds) >= 3 else None)
        self.bars_card.set_subtitle(tr("Lus jusqu'à la dernière page dans le lecteur"))
        self.bars_card.set_table(rows)

    def _refresh_facts(self):
        r = self.report
        while self.facts_grid.count():
            self.facts_grid.takeAt(0).widget().deleteLater()
        facts = []
        if r.rank is not None:
            place = (tr("Série la plus lue") if r.rank == 1
                     else tr("{rank}e série la plus lue", rank=r.rank))
            facts.append((tr("Place"), place + " · " + tr("{n} % de votre temps",
                                                          n=round(100 * r.share))))
        if r.last_day is not None:
            ago = (self.today - r.last_day).days
            facts.append((tr("Dernière lecture"), tr("aujourd'hui") if ago == 0
                          else tr("hier") if ago == 1 else fmt_day(r.last_day)))
        if r.best_day is not None:
            facts.append((tr("Plus grosse journée"),
                          tr("{duration}, le {day}", duration=stats.fmt_duration(r.best_day.seconds),
                             day=fmt_day(r.best_day.start))))
        done = [v for v in r.volumes if v.item.status == ss.FINISHED and v.seconds]
        if len(done) >= 2:
            longest = max(done, key=lambda v: v.seconds)
            quickest = min(done, key=lambda v: v.seconds)
            facts.append((tr("Le plus long"), f"{item_name(longest.item)} · "
                          + stats.fmt_duration(longest.seconds)))
            facts.append((tr("Le plus rapide"), f"{item_name(quickest.item)} · "
                          + stats.fmt_duration(quickest.seconds)))
        total = sum(s for _n, s in r.devices)
        if len(r.devices) > 1 and total:
            facts.append((tr("Appareils"), " · ".join(f"{name} {round(100 * s / total)} %"
                                                      for name, s in r.devices)))
        if not facts:
            facts.append((tr("Aucune lecture"), tr("Ouvrez un tome de la série : ses chiffres "
                                                   "apparaîtront ici.")))
        for row, (label, value) in enumerate(facts):
            lab = QLabel(label)
            lab.setObjectName("cardSub")
            val = QLabel(value)
            val.setTextFormat(Qt.PlainText)     # noms d'appareils : texte brut
            val.setWordWrap(True)
            self.facts_grid.addWidget(lab, row, 0, Qt.AlignTop)
            self.facts_grid.addWidget(val, row, 1, Qt.AlignTop)
        self.facts_grid.setRowStretch(len(facts), 1)
