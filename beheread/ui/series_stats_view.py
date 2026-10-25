"""Vue « statistiques d'une serie », dans la fenetre Statistiques (voir
stats_view.py, qui l'affiche a la place de la vue generale et lui prete sa
feuille de style).

Hierarchie, de haut en bas (maquette validee le 2026-10-25) :

1. quatre chiffres cles : le temps passe, ce que prend un tome (mediane),
   la vitesse comparee a votre moyenne, ce qui reste a lire ;
2. l'avancement : une case par tome du parcours de lecture (tomes virtuels
   compris, jamais leurs chapitres), lus dans le lecteur ou avant ;
3. le temps de chaque tome lu dans le lecteur (avec ses secondes par page),
   le carnet des jours de lecture et quelques reperes.

Seule la lecture compte, jamais la possession. Les calculs sont dans
core/series_stats.py ; ce module ne fait que dessiner un SeriesReport.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from beheread.core import series_stats as ss
from beheread.core import stats, units
from beheread.i18n import N_, fmt_decimal, tr, trn
from beheread.ui.charts import (
    _AMBER,
    BarChart,
    ChartCard,
    Shelf,
    StatTile,
    _fmt_int,
    day_name,
    fmt_day,
    fmt_estimate,
    fmt_pace,
)

JOURNAL_ROWS = 6    # jours du carnet ; le tableau les donne tous

# etat d'une case de l'etagere : termine lu dans le lecteur, termine avant
# le journal (ou marque lu), en cours, a lire
HERE, BEFORE = "here", "before"

_STATUS = {HERE: N_("Lu dans le lecteur"), BEFORE: N_("Lu avant le journal ou marqué lu"),
           ss.READING: N_("En cours"), ss.UNREAD: N_("À lire")}


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


# selon le contenu de la serie : (« un tome vous prend », singulier, pluriel,
# lus sur le total)
_COUNTED = {
    "volumes": (N_("Un tome vous prend"), N_("{n} tome"), N_("{n} tomes"),
                (N_("{done} / {n} tome lu"), N_("{done} / {n} tomes lus"))),
    "chapters": (N_("Un chapitre vous prend"), N_("{n} chapitre"), N_("{n} chapitres"),
                 (N_("{done} / {n} chapitre lu"), N_("{done} / {n} chapitres lus"))),
    "mixed": (N_("Un titre vous prend"), N_("{n} titre"), N_("{n} titres"),
              (N_("{done} / {n} titre lu"), N_("{done} / {n} titres lus")))}


def _mix(a, b, t) -> str:
    """Couleur entre a et b (t = 0 : a, t = 1 : b)."""
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t)).name()


def _speed(pages_per_minute) -> str:
    """« 7 », « 6,7 » : une decimale, sauf si elle est nulle."""
    value = round(pages_per_minute, 1)
    return _fmt_int(value) if value == int(value) else fmt_decimal(value)


def _day_label(day, today) -> str:
    return day_name(day.weekday()) + " " + fmt_day(day, year=day.year != today.year)


class SeriesStatsView(QWidget):
    def __init__(self, colors, data_colors, parent=None):
        super().__init__(parent)
        self.c, self.dc = colors, data_colors
        self.report = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # --- chiffres cles
        self.tiles = [StatTile(tr("Temps passé")), StatTile(tr("Un tome vous prend")),
                      StatTile(tr("Vitesse")), StatTile(tr("Reste à lire"))]
        tiles = QWidget()
        grid = QGridLayout(tiles)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        for i, tile in enumerate(self.tiles):
            grid.addWidget(tile, 0, i)
            grid.setColumnStretch(i, 1)
        v.addWidget(tiles)

        # --- avancement
        self.colors = {HERE: data_colors["finished"],
                       BEFORE: _mix(data_colors["finished"], colors["panel"], 0.6),
                       ss.READING: data_colors["reading"], ss.UNREAD: data_colors["unread"]}
        self.shelf = Shelf(self.colors, colors)
        self.shelf_sum = QLabel()
        self.shelf_sum.setObjectName("shelfSum")
        self.shelf_card = QFrame()
        self.shelf_card.setObjectName("card")
        row = QHBoxLayout(self.shelf_card)
        row.setContentsMargins(18, 14, 18, 10)
        row.setSpacing(18)
        row.addWidget(self.shelf_sum, 0, Qt.AlignTop)
        row.addWidget(self.shelf, 1)
        v.addWidget(self.shelf_card)

        # --- tome par tome, carnet, reperes
        self.bars = BarChart(data_colors["activity"], colors, ticks=stats.time_ticks,
                             value_fmt=lambda s: stats.fmt_duration(s, compact=True),
                             empty_text=tr("Aucun tome lu en entier dans le lecteur pour "
                                           "l'instant."),
                             height=190, label_all=True, bar_max=40)
        self.bars_card = ChartCard(tr("Tome par tome"), self.bars,
                                   [tr("Tome"), tr("Temps"), tr("Pages"), tr("s / page"),
                                    tr("Séances")])
        self.journal = QWidget()
        self.journal_grid = QGridLayout(self.journal)
        self.journal_grid.setContentsMargins(0, 4, 0, 0)
        self.journal_grid.setHorizontalSpacing(12)
        self.journal_grid.setVerticalSpacing(10)
        self.journal_grid.setColumnStretch(2, 1)
        self.journal_card = ChartCard(tr("Carnet"), self.journal,
                                      [tr("Jour"), tr("Temps"), tr("Pages"), tr("Séances"),
                                       tr("Terminés")])
        self.facts = QWidget()
        self.facts_grid = QGridLayout(self.facts)
        self.facts_grid.setContentsMargins(0, 4, 0, 0)
        self.facts_grid.setHorizontalSpacing(14)
        self.facts_grid.setVerticalSpacing(9)
        self.facts_grid.setColumnStretch(1, 1)
        self.facts_card = ChartCard(tr("Repères"), self.facts)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self.bars_card, 6)
        row.addWidget(self.journal_card, 5)
        row.addWidget(self.facts_card, 4)
        v.addLayout(row, 1)

    # ------------------------------------------------------------ mise a jour
    def caption(self) -> str:
        """Ligne sous le titre : auteur et jours de lecture."""
        r = self.report
        parts = [r.holdings.author] if r.holdings.author else []
        if r.first_day is None:
            parts.append(tr("pas encore lue dans le lecteur"))
        elif r.first_day == r.last_day:
            parts.append(tr("lue le {day}", day=fmt_day(r.first_day)))
        else:
            parts.append(tr("lue du {start} au {end}", start=fmt_day(r.first_day),
                            end=fmt_day(r.last_day)))
        return " · ".join(parts)

    def set_report(self, report, today):
        self.report, self.today = report, today
        self.counted = _COUNTED[_content(report.holdings.items)]
        self._refresh_tiles()
        self._refresh_shelf()
        self._refresh_bars()
        self._refresh_journal()
        self._refresh_facts()

    def _refresh_tiles(self):
        r = self.report
        spent, unit, speed, left = self.tiles
        if r.seconds:
            spent.set_content(stats.fmt_duration(r.seconds), "", " · ".join(
                [trn(r.pages, "{n} page", "{n} pages")]
                + ([trn(r.active_days, "{n} jour de lecture", "{n} jours de lecture")]
                   if r.active_days else [])))
        else:
            spent.set_content("–", "", tr("pas encore lue dans le lecteur"))

        label, one, many, _read = self.counted
        unit.set_label(tr(label))
        done = r.read_here
        if done:
            quick = min(done, key=lambda v: v.seconds)
            slow = max(done, key=lambda v: v.seconds)
            sub = (tr("en médiane, de {quick} ({quick_name}) à {slow} ({slow_name})",
                      quick=stats.fmt_duration(quick.seconds), quick_name=item_name(quick.item),
                      slow=stats.fmt_duration(slow.seconds), slow_name=item_name(slow.item))
                   if len(done) > 1 else item_name(quick.item))
            unit.set_content(stats.fmt_duration(r.median_seconds()), "", sub)
        else:
            unit.set_content("–", "", tr("Rien n'a encore été lu en entier dans le lecteur."))

        if r.pace:
            sub = tr("comme votre moyenne")
            if r.library_pace:
                diff = round(100 * (r.library_pace / r.pace - 1))
                average = _speed(60 / r.library_pace)
                if diff > 0:
                    sub = tr("{n} % plus rapide que votre moyenne ({speed})", n=diff,
                             speed=average)
                elif diff < 0:
                    sub = tr("{n} % plus lent que votre moyenne ({speed})", n=-diff,
                             speed=average)
            speed.set_content(tr("{n} pages / min", n=_speed(60 / r.pace)), "", sub,
                              fmt_pace(r.pace))
        else:
            speed.set_content("–", "", tr("Pas encore assez de pages lues dans la série pour "
                                          "mesurer son rythme."))

        if not r.remaining_items:
            left.set_content(tr("Rien"), "", tr("Tout est lu."))
            return
        lines = [trn(r.remaining_items, one, many)]
        if r.remaining_days:
            days = max(1, round(r.remaining_days))
            lines.append(trn(days, "environ {n} jour de lecture à votre rythme",
                             "environ {n} jours de lecture à votre rythme"))
        tip = (trn(r.unknown_pages, "Hors {n} titre au nombre de pages inconnu.",
                   "Hors {n} titres au nombre de pages inconnu.") if r.unknown_pages else "")
        value = "≈ " + fmt_estimate(r.remaining_seconds) if r.remaining_seconds else "–"
        left.set_content(value, "", " · ".join(lines), tip)

    def _state(self, v) -> str:
        if v.item.status == ss.FINISHED:
            return HERE if v.read_here else BEFORE
        return v.item.status

    def _refresh_shelf(self):
        r = self.report
        items, counts = [], {}
        pace = r.pace or r.library_pace
        for v in r.volumes:
            item, state = v.item, self._state(v)
            counts[state] = counts.get(state, 0) + 1
            tip = f"{item_name(item)} · {tr(_STATUS[state])}"
            if v.read_here:
                tip += "\n" + stats.fmt_duration(v.seconds) + " · " + trn(v.pages, "{n} page",
                                                                          "{n} pages")
            if v.finished_on:
                tip += "\n" + tr("terminé le {day}", day=fmt_day(v.finished_on))
            if item.status == ss.READING and item.total:
                tip += " · " + tr("page {page} / {total}", page=item.page + 1, total=item.total)
            if item.status == ss.UNREAD and item.total and pace:
                tip += "\n≈ " + stats.fmt_duration(item.total * pace)
            progress = item.page / item.total if item.total else 0.0
            label = units.fmt_number(item.number) if item.number is not None else "·"
            items.append((label, state, progress, tip))
        labels = ((HERE, "{n} lu dans le lecteur", "{n} lus dans le lecteur"),
                  (BEFORE, "{n} lu avant le journal ou marqué lu",
                   "{n} lus avant le journal ou marqués lus"),
                  (ss.READING, "{n} en cours", "{n} en cours"),
                  (ss.UNREAD, "{n} à lire", "{n} à lire"))
        self.shelf.set_items(items, [(trn(counts[s], one, many), s)
                                     for s, one, many in labels if counts.get(s)])
        one, many = self.counted[3]
        self.shelf_sum.setText(trn(len(r.volumes), one, many, done=_fmt_int(r.finished)))

    def _refresh_bars(self):
        r = self.report
        bars, paces, sittings, rows = [], [], [], []
        for v in r.read_here:
            label = units.fmt_number(v.item.number) if v.item.number is not None else "·"
            tip = (f"{stats.fmt_duration(v.seconds)}\n{item_name(v.item)} · "
                   + trn(v.pages, "{n} page", "{n} pages")
                   + (" · " + fmt_pace(v.pace) if v.pace else "")
                   + ("\n" + tr("lu d'une traite") if v.one_sitting else ""))
            bars.append((label, v.seconds, tip))
            paces.append(fmt_decimal(v.pace) if v.pace else "")
            sittings.append(tr("d'une traite") if v.one_sitting else "")
            rows.append((item_name(v.item), stats.fmt_duration(v.seconds), _fmt_int(v.pages),
                         fmt_decimal(v.pace) if v.pace else "", _fmt_int(v.sessions)))
        notes = [(tr("s / page"), paces, _AMBER)] if bars else []
        if any(sittings):
            notes.append(("", sittings, None))
        # mediane : un trait, son libelle dans le sous-titre (les valeurs des
        # barres sont deja ecrites au-dessus d'elles)
        median = r.median_seconds() if len(bars) >= 3 else 0
        self.bars.set_bars(bars, (median, "") if median else None, notes)
        before = sum(1 for v in r.volumes if self._state(v) == BEFORE)
        sub = tr("Tomes lus dans le lecteur")
        if median:
            sub += " · " + tr("médiane {duration} en pointillés",
                              duration=stats.fmt_duration(median))
        if before:
            sub += " · " + trn(before, "{n} autre lu avant le journal ou marqué lu",
                               "{n} autres lus avant le journal ou marqués lus")
        self.bars_card.set_subtitle(sub)
        self.bars_card.set_table(rows)

    def _chips(self, items, filled) -> str:
        """Numeros des tomes en pastilles (texte riche)."""
        color = self.dc["finished"] if filled else self.dc["unread"]
        out = []
        for item in items:
            label = units.fmt_number(item.number) if item.number is not None else "·"
            out.append(f'<span style="background-color:{color};color:#ffffff">&nbsp;{label}&nbsp;</span>'
                       if filled else f'<span style="color:{color}">[{label}]</span>')
        return " ".join(out)

    def _entry_text(self, e) -> str:
        dim = self.c["text_dim"]
        details = [trn(e.pages, "{n} page", "{n} pages"),
                   trn(e.sessions, "{n} séance", "{n} séances")]
        if e.finished:
            head = (tr("{name} terminé", name=item_name(e.finished[0])) if len(e.finished) == 1
                    else tr("{count} terminés", count=trn(len(e.finished), *self.counted[1:3])))
            head += " " + self._chips(e.finished, True)
            if e.started:
                details.append(", ".join(item_name(i) for i in e.started) + " "
                               + trn(len(e.started), "commencé", "commencés"))
        elif e.started:
            head = (", ".join(item_name(i) for i in e.started) + " "
                    + trn(len(e.started), "commencé", "commencés"))
        else:
            head = tr("Lecture")
        if e.started:
            head += " " + self._chips(e.started, False)
        return f'{head}<br><span style="color:{dim}">{" · ".join(details)}</span>'

    def _refresh_journal(self):
        r = self.report
        while self.journal_grid.count():
            self.journal_grid.takeAt(0).widget().deleteLater()
        cells = []
        for e in r.journal[:JOURNAL_ROWS]:
            if isinstance(e, ss.DayEntry):
                cells.append((_day_label(e.day, self.today), stats.fmt_duration(e.seconds),
                              self._entry_text(e), False))
            else:
                day = (fmt_day(e.first, year=False) if e.first == e.last
                       else tr("{start} – {end}", start=fmt_day(e.first, year=False),
                               end=fmt_day(e.last, year=False)))
                cells.append((day, stats.fmt_duration(e.seconds, compact=True),
                              trn(e.count, "{n} coup d'œil, non compté",
                                  "{n} coups d'œil, non comptés"), True))
        if not cells:
            cells.append(("", "", tr("Ouvrez un tome de la série : vos jours de lecture "
                                     "apparaîtront ici."), True))
        for row, (day, duration, text, dim) in enumerate(cells):
            lab = QLabel(day)
            lab.setObjectName("cardSub")
            dur = QLabel(duration)
            dur.setObjectName("cardSub" if dim else "journalTime")
            what = QLabel(text)
            what.setWordWrap(True)
            if dim:
                what.setObjectName("cardSub")
                what.setTextFormat(Qt.PlainText)
            else:
                what.setTextFormat(Qt.RichText)
            self.journal_grid.addWidget(lab, row, 0, Qt.AlignTop)
            self.journal_grid.addWidget(dur, row, 1, Qt.AlignTop)
            self.journal_grid.addWidget(what, row, 2, Qt.AlignTop)
        self.journal_grid.setRowStretch(len(cells), 1)
        hidden = len(r.journal) - JOURNAL_ROWS
        self.journal_card.set_subtitle(
            tr("Jours de lecture, du plus récent au plus ancien")
            + (" · " + trn(hidden, "{n} de plus dans le tableau", "{n} de plus dans le tableau")
               if hidden > 0 else ""))
        self.journal_card.set_table([
            (fmt_day(e.day), stats.fmt_duration(e.seconds), _fmt_int(e.pages),
             _fmt_int(e.sessions), ", ".join(units.fmt_number(i.number) for i in e.finished
                                             if i.number is not None))
            for e in r.journal if isinstance(e, ss.DayEntry)])

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
            best = r.best_day
            text = stats.fmt_duration(best.seconds)
            if best.finished:
                text += ", " + trn(len(best.finished), "{n} terminé", "{n} terminés")
            facts.append((tr("Plus grosse journée"),
                          tr("{what} · le {day}", what=text, day=fmt_day(best.day, year=False))))
        done = r.read_here
        if done:
            sitting = sum(1 for v in done if v.one_sitting)
            facts.append((tr("D'une traite"), tr("{n} sur {total}", n=sitting, total=len(done))))
        if r.sessions:
            facts.append((tr("Séance type"),
                          tr("{duration}, {pages}", duration=stats.fmt_duration(r.session_seconds),
                             pages=trn(round(r.session_pages), "{n} page", "{n} pages"))))
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
