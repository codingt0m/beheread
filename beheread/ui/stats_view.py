"""Fenetre « Statistiques de lecture ».

Hierarchie de l'ecran, de haut en bas :

1. le choix de la periode (7 jours, 30 jours, 12 mois, tout), seul filtre,
   au-dessus de tout ce qu'il gouverne, et la legende de ce qui est compare ;
2. les chiffres cles : le temps de lecture en chiffre principal, puis pages,
   tomes termines et jours de lecture, chacun avec son ecart a la periode
   precedente et une mini-tendance ;
3. le detail : temps de lecture dans le temps et series les plus lues, puis
   regularite (calendrier) et derniers tomes termines ;
4. l'etat actuel de la bibliotheque, qui ne depend pas de la periode (sa
   carte le dit).

La fenetre s'ouvre en plein ecran et tout tient sur cet ecran, sans
defilement : les cartes s'etirent pour occuper la hauteur, leurs listes
n'affichent que les lignes qui y tiennent, et la seconde rangee est retiree
quand l'ecran n'est pas assez haut (voir StatsDialog.fit_height).

Les requetes sont dans reading_log.py, les calculs dans stats.py (purs,
testes) ; ce module ne fait que dessiner le rapport (stats.Report). Les
composants sont construits une fois puis mis a jour en place : changer de
periode ne deplace rien et ne perd pas la bascule « Tableau ».

Choix de visualisation :
* une forme par question : un chiffre pour un total, un histogramme pour une
  grandeur dans le temps, un calendrier pour la regularite, une jauge pour un
  ratio, un classement pour des series, une liste pour des evenements rares
  (les tomes termines) ;
* une seule teinte par graphique (couleur d'accent = activite de lecture,
  vert = tomes termines), la meme signification partout ; le calendrier
  decline l'accent du clair au fonce ;
* barres fines (<= 24 px) arrondies en haut, carrees a la base, separees par
  au moins 2 px ; grille en traits fins pleins et discrets ;
* une seule valeur ecrite directement (le maximum) : le survol (souris ou
  clavier) donne chaque valeur, et un tableau les liste toutes ;
* la repartition non lus / en cours / termines a une legende, les couleurs
  ont ete validees (daltonisme, contraste) sur les fonds clair et sombre.
"""

import datetime as dt
from pathlib import PureWindowsPath

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from beheread.core import stats, units
from beheread.core.reading_session import MIN_DWELL, PAUSE_CAP
from beheread.i18n import fmt_decimal, tr, trn
from beheread.ui import style, theme
from beheread.ui.charts import (
    BarChart,
    CalendarHeatmap,
    ChartCard,
    FinishedList,
    HBarList,
    Meter,
    Sparkline,
    StackedBar,
    StatTile,
    _fmt_int,
    data_colors,
    month_name,
)
from beheread.ui.recap import RecapDialog


def _fmt_day(d, year=True) -> str:
    day = tr("1er") if d.day == 1 else str(d.day)
    if year:
        return tr("{day} {month} {year}", day=day, month=month_name(d.month), year=d.year)
    return tr("{day} {month}", day=day, month=month_name(d.month))


def _fmt_range(start, end) -> str:
    if start == end:
        return _fmt_day(end)
    return f"{_fmt_day(start, year=start.year != end.year)} – {_fmt_day(end)}"


def _comparable(report, since) -> bool:
    """La periode precedente est-elle couverte par la mesure (`since` : son
    premier jour) ? Sinon, on ne compare pas plutot que d'afficher une
    hausse trompeuse."""
    previous = report.period.previous
    return previous is not None and since is not None and since <= previous[1]


def _delta(current, previous, short, full, report, since) -> tuple:
    """Ecart avec la periode precedente : (texte court de la tuile, phrase
    complete de son infobulle). `short` et `full` mettent l'ecart en forme."""
    period = report.period
    if previous is None or period.previous is None:
        return "", ""
    if not _comparable(report, since):
        return "", (tr("Mesuré depuis le {day} : rien à comparer sur les {previous}.",
                       day=since.strftime(tr("%d/%m/%Y")), previous=period.previous_label)
                    if since else "")
    diff = current - previous
    if not diff:
        return ("= " + tr("identique"),
                tr("Autant que les {previous} ({value}).", previous=period.previous_label,
                   value=full(previous)))
    sentence = (tr("{diff} de plus que les {previous} ({value}).") if diff > 0
                else tr("{diff} de moins que les {previous} ({value})."))
    return (f"{'▲' if diff > 0 else '▼'} {short(abs(diff))}",
            sentence.format(diff=full(abs(diff)), previous=period.previous_label,
                            value=full(previous)))


def _caption(report) -> str:
    """Sous le titre : les dates de la periode et ce a quoi elle est
    comparee, dit une fois pour toutes les tuiles."""
    period = report.period
    span = _fmt_range(period.start, period.end)
    if period.previous is None or report.first_day is None:
        return span
    if not _comparable(report, report.first_day):
        return f"{span} · " + tr("historique trop court pour comparer")
    return f"{span} · " + tr("comparé aux {previous}", previous=period.previous_label)


def _bucket_name(bucket, grain, short=False) -> str:
    d = bucket.start
    if grain == "month":
        return f"{month_name(d.month)} {d.year}"
    return d.strftime(tr("%d/%m") if short else tr("%d/%m/%Y"))


def _axis_labels(buckets, grain) -> list:
    """Etiquettes de l'axe du temps : toutes s'il y a peu de barres, sinon
    une sur n en partant de la plus recente (qui est toujours etiquetee)."""
    n = len(buckets)
    limit = 12 if grain == "month" else 7
    step = max(1, -(-n // limit))
    labels = []
    for i, b in enumerate(buckets):
        if (n - 1 - i) % step:
            labels.append("")
        elif grain == "month":
            year = f" {b.start.year % 100:02d}" if b.start.month == 1 else ""
            labels.append(month_name(b.start.month) + year)
        else:
            labels.append(tr("{day}/{month}", day=b.start.day, month=b.start.month))
    return labels


def _fmt_pace(seconds) -> str:
    text = f"{seconds:.0f}" if seconds >= 10 else fmt_decimal(seconds)
    return tr("{seconds} s par page", seconds=text)


# ---------------------------------------------------------------- fenetre

class StatsDialog(QDialog):
    def __init__(self, store, library, mode, parent=None, today=None, resolve=None,
                 titles=None):
        """library : etat de la bibliotheque - {"unread": n, "reading": n,
        "finished": n} et, pour le temps restant a lire, "remaining_pages"
        (pages non lues des tomes non termines) et "unknown_pages" (tomes
        dont le nombre de pages est inconnu).
        resolve : empreinte d'un tome -> (cle de serie, nom affiche) selon la
        bibliotheque actuelle, ou None (voir stats.top_series).
        titles : {empreinte: titre actuel du tome} (liste des tomes termines)."""
        super().__init__(parent)
        self.setWindowTitle(tr("Statistiques de lecture"))
        self.store = store
        self.library = library
        self.resolve = resolve
        self.titles = titles or {}
        self.today = today or dt.date.today()
        self.c = c = theme.colors(mode)
        self.dc = data_colors(mode)
        self.report = None

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 18, 22, 18)
        self.root.setSpacing(14)
        # la fenetre a la taille de l'ecran : c'est le contenu qui s'y adapte
        # (voir fit_height), jamais la fenetre qui grandit avec son contenu
        self.root.setSizeConstraint(QLayout.SetNoConstraint)
        self.root.addLayout(self._build_header())
        self._build_body()

        self.setStyleSheet(f"""
            QDialog {{ background: {c['window']}; }}
            QLabel {{ color: {c['text']}; }}
            QToolTip {{
                color: {c['text']}; background: {c['panel']};
                border: 1px solid {c['border']}; padding: 4px 6px;
            }}
            #statsTitle {{ font-size: 20px; font-weight: 700; }}
            #tile, #card {{
                background: {c['panel']}; border: 1px solid {c['border']}; border-radius: {style.RADIUS_MD}px;
            }}
            #tileLabel {{ color: {c['text_dim']}; font-size: 12px; }}
            #tileValue {{ font-size: 24px; font-weight: 600; }}
            #heroValue {{ font-size: 44px; font-weight: 600; }}
            #tileDelta {{ font-size: 13px; }}
            #tileSub, #cardSub, #caption {{ color: {c['text_dim']}; font-size: 12px; }}
            #cardTitle {{ font-size: 14px; font-weight: 700; }}
            #backlogValue {{ font-size: 24px; font-weight: 600; }}
            #emptyTitle {{ font-size: 15px; font-weight: 600; }}
            QPushButton {{
                color: {c['text']}; background: {c['button']};
                border: 1px solid {c['border']}; border-radius: 8px; padding: 5px 14px;
            }}
            QPushButton:hover {{ background: {c['button_hover']}; }}
            QPushButton:focus {{ border: 2px solid {theme.ACCENT}; }}
            QPushButton#toggle {{ padding: 2px 10px; font-size: 12px; }}
            QPushButton#link {{
                background: transparent; border: none; padding: 2px 0;
                color: {c['text_dim']}; font-size: 12px; text-decoration: underline;
            }}
            QPushButton#link:hover {{ color: {c['text']}; }}
            QPushButton#seg {{
                padding: 5px 14px; font-size: 12px; border-radius: 0; margin-left: -1px;
            }}
            QPushButton#seg[segPos="first"] {{
                margin-left: 0; border-top-left-radius: 8px; border-bottom-left-radius: 8px;
            }}
            QPushButton#seg[segPos="last"] {{
                border-top-right-radius: 8px; border-bottom-right-radius: 8px;
            }}
            QPushButton#seg:checked {{
                background: {theme.ACCENT_SOFT}; border: 1px solid {theme.ACCENT};
            }}
            QTableWidget {{
                color: {c['text']}; background: {c['panel']};
                gridline-color: {c['border']}; border: none;
            }}
            QHeaderView::section {{
                color: {c['text_dim']}; background: {c['panel']};
                border: none; border-bottom: 1px solid {c['border']}; padding: 4px;
            }}
        """)
        # plein ecran, sur l'ecran de la bibliotheque
        screen = parent.screen() if parent is not None else QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.setWindowState(self.windowState() | Qt.WindowFullScreen)
        self.set_period(store.ui_pref("stats_period", stats.DEFAULT_PERIOD))

    # ------------------------------------------------------------ construction
    def _build_header(self):
        """En-tete : titre, choix de la periode (qui gouverne tout ce qui
        suit), fermeture ; dessous, les dates de la periode et l'acces a la
        methode de mesure."""
        v = QVBoxLayout()
        v.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel(tr("Statistiques de lecture"))
        title.setObjectName("statsTitle")
        head.addWidget(title)
        head.addStretch(1)

        segmented = QWidget()
        seg = QHBoxLayout(segmented)
        seg.setContentsMargins(0, 0, 0, 0)
        seg.setSpacing(0)
        self.period_buttons = {}
        group = QButtonGroup(self)
        for i, (key, label) in enumerate(stats.PERIODS):
            btn = QPushButton(tr(label))
            btn.setObjectName("seg")
            # pas « pos » : propriete Qt de QWidget (une position), l'ecriture
            # echouait sans bruit et les extremites n'etaient jamais arrondies
            btn.setProperty("segPos", "first" if i == 0 else
                            ("last" if i == len(stats.PERIODS) - 1 else "mid"))
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.toggled.connect(lambda on, k=key: on and self._choose_period(k))
            group.addButton(btn)
            seg.addWidget(btn)
            self.period_buttons[key] = btn
        head.addWidget(segmented)
        recap = QPushButton(tr("Bilan de l'année"))
        recap.setToolTip(tr("Votre année de lecture en une image à partager"))
        recap.setCursor(Qt.PointingHandCursor)
        recap.clicked.connect(self._open_recap)
        head.addWidget(recap)
        # en plein ecran, il n'y a pas de barre de titre : la fermeture est ici
        self.close_button = QPushButton(tr("Fermer"))
        self.close_button.setToolTip(tr("Fermer les statistiques (Échap)"))
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.clicked.connect(self.accept)
        head.addWidget(self.close_button)
        v.addLayout(head)

        row = QHBoxLayout()
        self.caption = QLabel()
        self.caption.setObjectName("caption")
        row.addWidget(self.caption, 1)
        # la methode s'affiche en infobulle (survol ou clic) : elle ne prend
        # aucune place a l'ecran
        self.method = QPushButton(tr("Méthode de mesure"))
        self.method.setObjectName("link")
        self.method.setCursor(Qt.PointingHandCursor)
        self.method.setToolTip(
            "<qt>" + tr("Une page compte comme lue après {dwell} s d'affichage (feuilleter ne "
                        "compte pas) ; le temps de lecture ignore les pauses de plus de {pause} s. "
                        "Un tome est terminé quand sa dernière page est atteinte dans le lecteur : "
                        "« Marquer comme lu » ne compte pas comme une lecture.",
                        dwell=f"{MIN_DWELL:.0f}", pause=f"{PAUSE_CAP:.0f}") + "</qt>")
        self.method.clicked.connect(lambda: QToolTip.showText(
            self.method.mapToGlobal(QPoint(0, self.method.height())),
            self.method.toolTip(), self.method))
        row.addWidget(self.method)
        v.addLayout(row)
        return v

    def _open_recap(self):
        RecapDialog(self.store.reading_log, self.c, self.today, self.resolve, self).exec()

    def _build_body(self):
        c, dc = self.c, self.dc

        # --- etat vide : un seul message, a la place des chiffres et graphiques
        self.empty_card = QFrame()
        self.empty_card.setObjectName("card")
        ev = QVBoxLayout(self.empty_card)
        ev.setContentsMargins(24, 28, 24, 28)
        ev.setSpacing(6)
        empty_title = QLabel(tr("Aucune lecture enregistrée pour l'instant"))
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_text = QLabel(tr("Ouvrez un tome : le temps de lecture, les pages lues et les tomes "
                               "terminés apparaîtront ici au fil de vos lectures."))
        empty_text.setObjectName("cardSub")
        empty_text.setAlignment(Qt.AlignCenter)
        empty_text.setWordWrap(True)
        ev.addStretch(1)
        ev.addWidget(empty_title)
        ev.addWidget(empty_text)
        ev.addStretch(1)
        self.root.addWidget(self.empty_card, 1)

        # --- chiffres cles
        self.pages_spark = Sparkline(dc["activity"], c)
        self.finished_spark = Sparkline(dc["finished"], c)
        self.days_meter = Meter(dc["activity"])
        self.tiles = [StatTile(tr("Temps de lecture"), hero=True),
                      StatTile(tr("Pages lues"), self.pages_spark),
                      StatTile(tr("Tomes terminés"), self.finished_spark),
                      StatTile(tr("Jours de lecture"), self.days_meter)]
        self.tiles_host = QWidget()
        grid = QGridLayout(self.tiles_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.addWidget(self.tiles[0], 0, 0, 1, 2)    # chiffre principal : double largeur
        for i, tile in enumerate(self.tiles[1:]):
            grid.addWidget(tile, 0, 2 + i)
        for col in range(5):
            grid.setColumnStretch(col, 1)
        self.root.addWidget(self.tiles_host)

        # --- premiere rangee : le temps de lecture et les series
        self.time_chart = BarChart(dc["activity"], c, ticks=stats.time_ticks,
                                   value_fmt=lambda s: stats.fmt_duration(s, compact=True),
                                   empty_text=tr("Aucune lecture enregistrée sur la période."))
        self.time_card = ChartCard(tr("Temps de lecture"), self.time_chart,
                                   [tr("Jour"), tr("Temps"), tr("Pages"), tr("Tomes terminés")])
        self.series_list = HBarList(dc["activity"], c, tr("Aucune lecture enregistrée sur la période."))
        self.series_card = ChartCard(tr("Séries les plus lues"), self.series_list)
        self.series_card.set_subtitle(tr("Part du temps de lecture"))
        self.detail = QWidget()
        row = QHBoxLayout(self.detail)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(self.time_card, 3)
        row.addWidget(self.series_card, 1)
        self.root.addWidget(self.detail, 1)

        # --- seconde rangee : regularite, tomes termines, bibliotheque. C'est
        # elle qui est retiree quand l'ecran n'est pas assez haut (fit_height).
        self.calendar = CalendarHeatmap(dc["activity"], c)
        self.calendar_card = ChartCard(tr("Régularité"), self.calendar)
        self.finished_list = FinishedList(dc["finished"], c, tr("Aucun tome terminé sur la période."))
        self.finished_card = ChartCard(tr("Tomes terminés"), self.finished_list)
        self.library_card = self._library_card()
        self.habits = QWidget()
        row = QHBoxLayout(self.habits)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(self.calendar_card, 2)
        row.addWidget(self.finished_card, 1)
        row.addWidget(self.library_card, 1)
        self.root.addWidget(self.habits, 1)

    def _library_card(self):
        """Etat actuel de la bibliotheque : il ne depend pas de la periode,
        et la carte le dit."""
        lib = self.library
        parts = [(tr("Terminés"), lib.get("finished", 0), self.dc["finished"]),
                 (tr("En cours"), lib.get("reading", 0), self.dc["reading"]),
                 (tr("Non lus"), lib.get("unread", 0), self.dc["unread"])]
        total = sum(n for _l, n, _c in parts)
        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        if total:
            v.addWidget(StackedBar(parts, self.c))
            v.addSpacing(8)
        label = QLabel(tr("Reste à lire"))
        label.setObjectName("tileLabel")
        value, detail = self._backlog()
        self.backlog_value = QLabel(value)
        self.backlog_value.setObjectName("backlogValue")
        self.backlog_value.setVisible(bool(value))
        self.backlog_detail = QLabel(detail)
        self.backlog_detail.setObjectName("cardSub")
        self.backlog_detail.setWordWrap(True)
        v.addWidget(label)
        v.addWidget(self.backlog_value)
        v.addWidget(self.backlog_detail)
        v.addStretch(1)
        card = ChartCard(tr("Bibliothèque"), body)
        card.set_subtitle((trn(total, "{n} tome", "{n} tomes") if total else tr("Vide"))
                          + " · " + tr("indépendant de la période"))
        return card

    def _backlog(self) -> tuple:
        """(chiffre, precision) du temps qu'il reste a lire dans la
        bibliotheque, au rythme habituel."""
        pace = self.store.reading_pace()
        remaining = self.library.get("remaining_pages", 0)
        if not pace:
            return "", (tr("Rythme de lecture pas encore mesuré : l'estimation s'affichera "
                           "après quelques pages lues."))
        if not remaining:
            return "", tr("Rien en attente. Votre rythme : {pace}.", pace=_fmt_pace(pace))
        seconds = remaining * pace
        # au-dela de dix heures, les minutes d'une estimation n'ont pas de sens
        duration = (f"{_fmt_int(round(seconds / 3600))} h" if seconds >= 36000
                    else stats.fmt_duration(seconds, compact=True))
        detail = trn(remaining, "{n} page à votre rythme de {pace}",
                     "{n} pages à votre rythme de {pace}", pace=_fmt_pace(pace))
        unknown = self.library.get("unknown_pages", 0)
        if unknown:
            detail += trn(unknown, ", hors {n} tome au nombre de pages inconnu",
                          ", hors {n} tomes au nombre de pages inconnu")
        return f"≈ {duration}", detail + "."

    # ------------------------------------------------------------ un seul ecran
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_height()

    def showEvent(self, event):
        super().showEvent(event)
        # une fois les cartes a leur largeur reelle (la hauteur de certaines
        # en depend), on verifie de nouveau que tout tient
        QTimer.singleShot(0, self.fit_height)

    def fit_height(self):
        """Tout tient sur un ecran, sans defilement. Les cartes s'etirent pour
        occuper la hauteur disponible, et leurs listes n'affichent que les
        lignes qui y tiennent ; quand meme leur hauteur minimale ne tient pas,
        la seconde rangee (regularite, tomes termines, bibliotheque) est
        retiree et la premiere garde toute la place."""
        if self.report is None or self.report.first_day is None:
            self.habits.setVisible(True)    # journal vide : le message et la bibliotheque
            return
        self.root.activate()
        needed = self.root.minimumSize().height()
        if self.habits.isHidden():
            needed += self.root.spacing() + self.habits.minimumSizeHint().height()
        self.habits.setVisible(needed <= self.height())

    # ------------------------------------------------------------ periode
    def _choose_period(self, key):
        if self.report is not None and self.report.period.key == key:
            return
        self.set_period(key)
        self.store.set_ui_pref("stats_period", self.report.period.key)

    def set_period(self, key):
        """Recalcule le rapport pour la periode et met a jour chaque
        composant en place."""
        self.report = stats.build_report(self.store.reading_log, key, self.today, self.resolve,
                                         top=HBarList.MAX_ROWS)
        self.period_buttons[self.report.period.key].setChecked(True)
        self._refresh(self.report)

    # ------------------------------------------------------------ mise a jour
    def _refresh(self, report):
        empty = report.first_day is None
        self.empty_card.setVisible(empty)
        for block in (self.tiles_host, self.detail, self.calendar_card, self.finished_card):
            block.setVisible(not empty)
        self.caption.setText(_caption(report))
        self._refresh_tiles(report)
        self._refresh_time(report)
        self._refresh_series(report)
        self._refresh_calendar(report)
        self._refresh_finished(report)
        self.fit_height()

    def _refresh_tiles(self, report):
        t, prev, period = report.totals, report.previous, report.period
        measured = report.first_session   # pages et temps ne sont mesures que depuis ce jour
        hero, pages, finished, days = self.tiles

        details = []
        if t.active_days and t.seconds:
            details.append(tr("{duration} par jour de lecture",
                              duration=stats.fmt_duration(t.seconds / t.active_days)))
        if t.sessions:
            details.append(trn(t.sessions, "{n} séance", "{n} séances"))
        # compare a la minute pres : un ecart de quelques secondes n'en est pas un
        delta, tip = _delta(round(t.seconds / 60) * 60, prev and round(prev.seconds / 60) * 60,
                            stats.fmt_duration, stats.fmt_duration, report, measured)
        hero.set_content(stats.fmt_duration(t.seconds), delta, " · ".join(details), tip)

        delta, tip = _delta(t.pages, prev and prev.pages, _fmt_int,
                            lambda n: trn(n, "{n} page", "{n} pages"), report, measured)
        if t.chapters:   # « dans 5 tomes · 12 chapitres »
            within = tr("dans {items}", items=units.count_text(t.volumes - t.chapters, t.chapters))
        else:
            within = trn(t.volumes, "dans {n} tome", "dans {n} tomes") if t.volumes else ""
        pages.set_content(_fmt_int(t.pages), delta, within, tip)
        self.pages_spark.set_values(b.pages for b in report.buckets)

        # tomes seuls ; les chapitres termines en sous-titre
        volumes = t.finished - t.finished_chapters
        delta, tip = _delta(volumes, prev and prev.finished - prev.finished_chapters, _fmt_int,
                            lambda n: trn(n, "{n} tome", "{n} tomes"), report, report.first_day)
        finished.set_content(_fmt_int(volumes), delta,
                             trn(t.finished_chapters, "+ {n} chapitre", "+ {n} chapitres")
                             if t.finished_chapters else "", tip)
        self.finished_spark.set_values(b.finished - b.finished_chapters for b in report.buckets)

        delta, tip = _delta(t.active_days, prev and prev.active_days, _fmt_int,
                            lambda n: trn(n, "{n} jour", "{n} jours"), report, measured)
        days.set_content(tr("{n} sur {total}", n=_fmt_int(t.active_days),
                            total=_fmt_int(period.days)), delta, "", tip)
        self.days_meter.set_ratio(t.active_days / period.days)

    def _refresh_time(self, report):
        grain = report.period.grain
        bars, rows = [], []
        for label, b in zip(_axis_labels(report.buckets, grain), report.buckets, strict=True):
            # la valeur d'abord, puis ce qui la situe
            detail = (f"{_bucket_name(b, grain, short=True)} · "
                      + trn(b.pages, "{n} page", "{n} pages"))
            if b.finished - b.finished_chapters:
                detail += " · " + trn(b.finished - b.finished_chapters,
                                      "{n} tome terminé", "{n} tomes terminés")
            if b.finished_chapters:
                detail += " · " + trn(b.finished_chapters,
                                      "{n} chapitre terminé", "{n} chapitres terminés")
            bars.append((label, b.seconds, f"{stats.fmt_duration(b.seconds)}\n{detail}"))
            rows.append((_bucket_name(b, grain), stats.fmt_duration(b.seconds),
                         _fmt_int(b.pages), _fmt_int(b.finished)))
        monthly = grain == "month"
        self.time_chart.set_bars(bars)
        self.time_card.set_title(tr("Temps de lecture par mois") if monthly
                                 else tr("Temps de lecture par jour"))
        self.time_card.set_table(list(reversed(rows)),
                                 [tr("Mois") if monthly else tr("Jour"), tr("Temps"), tr("Pages"),
                                  tr("Tomes terminés")])

    def _refresh_series(self, report):
        timed = any(s.seconds for s in report.series)
        self.series_list.set_rows(
            (s.name, s.seconds if timed else s.pages,
             (stats.fmt_duration(s.seconds, compact=True) if timed
              else trn(s.pages, "{n} page", "{n} pages"))
             + " · " + tr("{n} %", n=round(100 * s.share)))
            for s in report.series)

    def _refresh_calendar(self, report):
        self.calendar.set_days(report.calendar)
        streak = (trn(report.streak, "Série en cours : {n} jour", "Série en cours : {n} jours")
                  if report.streak else tr("Pas de série en cours"))
        if report.best_streak > report.streak:
            streak += " · " + trn(report.best_streak, "record : {n} jour", "record : {n} jours")
        if report.calendar and report.calendar[0].start > report.period.start:
            streak += " · " + tr("53 dernières semaines affichées")
        self.calendar_card.set_subtitle(streak)

    def _refresh_finished(self, report):
        items, unknown = [], {}   # unknown : jour -> position de sa ligne « tomes absents »
        for day, volume, title, series in report.finished_volumes:
            date = _fmt_day(day, year=day.year != self.today.year)
            name = self.titles.get(volume) or title or series
            if not name and not volume.startswith("c1:"):
                # ancienne entree indexee par chemin, peut-etre venue d'un autre
                # systeme (sauvegarde importee) : PureWindowsPath coupe sur \ et /
                name = PureWindowsPath(volume).stem
            if name:
                items.append((name, date, 1))
                continue
            # fichier supprime depuis, termine avant le journal : son titre est
            # perdu. Une seule ligne par jour plutot qu'une ligne identique par tome.
            if day not in unknown:
                unknown[day] = len(items)
                items.append(("", date, 0))
            count = items[unknown[day]][2] + 1
            items[unknown[day]] = (trn(count, "{n} tome absent de la bibliothèque",
                                       "{n} tomes absents de la bibliothèque"), date, count)
        total, chapters = report.totals.finished, report.totals.finished_chapters
        self.finished_list.set_items(items, total)
        if chapters:
            subtitle = tr("{items} lus jusqu'à la dernière page",
                          items=units.count_text(total - chapters, chapters))
        else:
            subtitle = trn(total, "{n} tome lu jusqu'à la dernière page",
                           "{n} tomes lus jusqu'à la dernière page") if total else ""
        self.finished_card.set_subtitle(subtitle)
