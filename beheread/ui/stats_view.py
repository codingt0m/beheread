"""Fenetre « Statistiques de lecture ».

Hierarchie de l'ecran, de haut en bas :

1. le choix de la periode (7 jours, 30 jours, 12 mois, tout), seul filtre,
   au-dessus de tout ce qu'il gouverne, et la legende de ce qui est compare ;
2. les chiffres cles : le temps de lecture en chiffre principal, puis pages,
   tomes termines et jours de lecture, chacun avec son ecart a la periode
   precedente ;
3. le detail : temps de lecture dans le temps et series les plus lues, puis
   regularite et derniers tomes termines ;
4. l'etat actuel de la bibliotheque, qui ne depend pas de la periode (sa
   carte le dit).

Un clic (ou Entree) sur une serie du classement ouvre ses statistiques dans
la meme fenetre (series_stats_view.py) ; « Statistiques » dans le fil
d'Ariane, ou Echap, ramene a la vue generale, sur la meme periode.

La fenetre est une fenetre normale, centree sur la bibliotheque la premiere
fois, puis rouverte a la taille et a la place ou on l'a laissee. Les cartes
s'etirent pour occuper la hauteur et leurs listes n'affichent que les lignes
qui y tiennent ; quand la fenetre est trop basse pour tout montrer, elle
defile et le dit (lien en bas) plutot que de retirer des cartes.

Les requetes sont dans reading_log.py, les calculs dans stats.py (purs,
testes) ; ce module ne fait que dessiner le rapport (stats.Report). Les
composants sont construits une fois puis mis a jour en place : changer de
periode ne deplace rien et ne perd pas la bascule « Tableau ».

Choix de visualisation :
* une forme par question : un chiffre pour un total, un histogramme pour une
  grandeur dans le temps, un calendrier pour la regularite (ou, sur 7 et 30
  jours, ou il repeterait l'histogramme, le temps moyen par jour de la
  semaine), une jauge pour un ratio, un classement pour des series, une
  liste pour des evenements rares (les tomes termines) ;
* une seule teinte par graphique (couleur d'accent = activite de lecture,
  vert = tomes termines), la meme signification partout ; le calendrier
  decline l'accent du clair au fonce ;
* barres fines (<= 24 px) arrondies en haut, carrees a la base, separees par
  au moins 2 px ; grille en traits fins pleins et discrets ;
* le classement est a l'echelle de 100 % : une serie qui fait 34 % du temps
  remplit 34 % de sa piste ;
* une seule valeur ecrite directement (le maximum) : le survol (souris ou
  clavier) donne chaque valeur, et un tableau les liste toutes ;
* la repartition non lus / en cours / termines a une legende, les couleurs
  ont ete validees (daltonisme, contraste) sur les fonds clair et sombre.
"""

import datetime as dt
from pathlib import PureWindowsPath

from PySide6.QtCore import QByteArray, QPoint, Qt
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
    QScrollArea,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from beheread.core import series_stats, stats, units
from beheread.core.reading_session import MIN_DWELL, PAUSE_CAP
from beheread.i18n import tr, trn
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
    day_name,
    fmt_day,
    fmt_estimate,
    fmt_pace,
    month_name,
)
from beheread.ui.recap import RecapDialog
from beheread.ui.series_stats_view import SeriesStatsView

# periodes ou le calendrier repeterait l'histogramme jour par jour : la
# carte « Regularite » y montre le temps moyen par jour de la semaine
SHORT_PERIODS = ("7d", "30d")


def _fmt_range(start, end) -> str:
    if start == end:
        return fmt_day(end)
    return f"{fmt_day(start, year=start.year != end.year)} – {fmt_day(end)}"


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


def _tip_button(text, tip, parent):
    """Lien discret dont l'infobulle s'affiche au survol comme au clic."""
    btn = QPushButton(text)
    btn.setObjectName("link")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip(tip)
    btn.clicked.connect(lambda: QToolTip.showText(
        btn.mapToGlobal(QPoint(0, btn.height())), btn.toolTip(), parent))
    return btn


# ---------------------------------------------------------------- fenetre

class _Page(QWidget):
    """Contenu d'une page qui defile, sans hauteur dependant de la largeur :
    QScrollArea la calculerait d'apres les tailles conseillees des textes a
    la ligne (pas leurs minimums) et ferait defiler un contenu qui tient.
    Place dans un widget intermediaire : QScrollArea interroge le layout de
    la page, et un layout interroge ce widget."""

    def hasHeightForWidth(self):
        return False


class StatsDialog(QDialog):
    def __init__(self, store, library, mode, parent=None, today=None, resolve=None,
                 titles=None, holdings=None, open_series=None, series=None):
        """library : etat de la bibliotheque - {"unread": n, "reading": n,
        "finished": n} et, pour le temps restant a lire, "remaining_pages"
        (pages non lues des tomes non termines) et "unknown_pages" (tomes
        dont le nombre de pages est inconnu) ; "remaining_by_volume"
        ({empreinte: pages restantes}) permet de compter chaque tome au
        rythme de sa serie plutot qu'au rythme moyen.
        resolve : empreinte d'un tome -> (cle de serie, nom affiche) selon la
        bibliotheque actuelle, ou None (voir stats.top_series).
        titles : {empreinte: titre actuel du tome} (liste des tomes termines).
        holdings : cle de serie -> series_stats.SeriesHoldings, ou None si ce
        n'est pas une serie de la bibliotheque ; sans lui, le classement
        n'ouvre rien. open_series(cle) : bouton « Ouvrir la serie » (la
        fenetre se ferme). series : cle de la serie a afficher d'emblee."""
        super().__init__(parent)
        self.setWindowTitle(tr("Statistiques de lecture"))
        self.store = store
        self.library = library
        self.resolve = resolve
        # cle de serie actuelle d'un tome : un tome range depuis dans une
        # autre serie n'est plus compte dans celle ou il a ete lu
        self.owner = (lambda volume: (resolve(volume) or (None,))[0]) if resolve else None
        self.titles = titles or {}
        self.holdings = holdings
        self.open_series = open_series
        self._holdings_cache = {}
        self.series_key = None
        self.today = today or dt.date.today()
        self.c = c = theme.colors(mode)
        self.dc = data_colors(mode)
        self.report = None

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 18, 22, 10)
        self.root.setSpacing(14)
        # c'est le contenu qui s'adapte a la fenetre, en defilant au besoin,
        # jamais la fenetre qui grandit avec lui
        self.root.setSizeConstraint(QLayout.SetNoConstraint)
        self.root.addLayout(self._build_header())
        self.pages = QStackedWidget()
        self.root.addWidget(self.pages, 1)
        self.body_layout = self._add_page()
        self._build_body()
        self.series_view = SeriesStatsView(c, self.dc)
        self._add_page().addWidget(self.series_view)
        # sur un ecran bas, ce qui est plus bas que l'ecran est annonce
        self.more = QPushButton(tr("↓ Régularité, tomes terminés et bibliothèque plus bas"))
        self.more.setObjectName("link")
        self.more.setCursor(Qt.PointingHandCursor)
        self.more.clicked.connect(lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))
        self.more.hide()
        self.root.addWidget(self.more, 0, Qt.AlignHCenter)
        bar = self.scroll.verticalScrollBar()
        bar.rangeChanged.connect(lambda *_: self._update_more())
        bar.valueChanged.connect(lambda *_: self._update_more())

        self.setStyleSheet(f"""
            QDialog {{ background: {c['window']}; }}
            QScrollArea, #statsPage {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
            QScrollBar::handle:vertical {{
                background: {c['border']}; border-radius: 5px; min-height: 40px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {c['text_dim']}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
            QLabel {{ color: {c['text']}; }}
            QToolTip {{
                color: {c['text']}; background: {c['panel']};
                border: 1px solid {c['border']}; padding: 4px 6px;
            }}
            #statsTitle {{ font-size: 20px; font-weight: 700; }}
            #crumbSep {{ font-size: 20px; color: {c['text_dim']}; }}
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
            #shelfSum {{ font-size: 15px; font-weight: 600; }}
            #journalTime {{ font-weight: 600; }}
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
            QPushButton#crumb {{
                background: transparent; border: none; padding: 0;
                color: {c['text_dim']}; font-size: 20px; text-decoration: underline;
            }}
            QPushButton#crumb:hover {{ color: {c['text']}; }}
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
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
        self._place(parent)
        self.set_period(store.ui_pref("stats_period", stats.DEFAULT_PERIOD))
        if series is not None:
            self.show_series(series)

    # ------------------------------------------------------------ taille et place
    GEOMETRY_PREF = "stats_geometry"
    DEFAULT_SIZE = (1320, 900)

    def _place(self, parent):
        """Taille et place laissees a la derniere fermeture ; sinon une
        grande fenetre centree sur la bibliotheque, dans l'ecran."""
        saved = self.store.ui_pref(self.GEOMETRY_PREF, "")
        if saved and self.restoreGeometry(QByteArray.fromBase64(saved.encode("ascii"))):
            return
        screen = parent.screen() if parent is not None else QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(*self.DEFAULT_SIZE)
            return
        area = screen.availableGeometry()
        self.resize(min(self.DEFAULT_SIZE[0], area.width() - 80),
                    min(self.DEFAULT_SIZE[1], area.height() - 60))
        center = parent.frameGeometry().center() if parent is not None else area.center()
        frame = self.frameGeometry()
        frame.moveCenter(center)
        x = max(area.left(), min(frame.left(), area.right() - frame.width()))
        y = max(area.top(), min(frame.top(), area.bottom() - frame.height()))
        self.move(x, y)

    def done(self, result):
        self.store.set_ui_pref(self.GEOMETRY_PREF,
                               bytes(self.saveGeometry().toBase64()).decode("ascii"))
        super().done(result)

    def _add_page(self):
        """Page de la fenetre, dans une zone qui defile quand l'ecran est
        trop bas : renvoie son layout."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName("statsPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        content = _Page()
        content.setObjectName("statsPage")
        outer.addWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(14)
        scroll.setWidget(page)
        self.pages.addWidget(scroll)
        if self.pages.count() == 1:
            self.scroll = scroll
        return layout

    # ------------------------------------------------------------ construction
    def _build_header(self):
        """En-tete : titre (ou fil d'Ariane d'une serie), choix de la
        periode (qui gouverne tout ce qui suit), fermeture ; dessous, les
        dates de la periode et l'acces a la methode de mesure."""
        v = QVBoxLayout()
        v.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.crumb = QPushButton(tr("Statistiques"))
        self.crumb.setObjectName("crumb")
        self.crumb.setCursor(Qt.PointingHandCursor)
        self.crumb.setToolTip(tr("Revenir aux statistiques de toute la lecture (Échap)"))
        self.crumb.clicked.connect(self.show_overview)
        self.crumb_sep = QLabel("›")
        self.crumb_sep.setObjectName("crumbSep")
        self.title = QLabel(tr("Statistiques de lecture"))
        self.title.setObjectName("statsTitle")
        self.title.setTextFormat(Qt.PlainText)    # nom de serie : texte brut
        for w in (self.crumb, self.crumb_sep):
            w.hide()
            head.addWidget(w)
        head.addWidget(self.title)
        head.addStretch(1)

        self.segmented = QWidget()
        seg = QHBoxLayout(self.segmented)
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
        head.addWidget(self.segmented)
        self.recap_button = QPushButton(tr("Bilan de l'année"))
        self.recap_button.setToolTip(tr("Votre année de lecture en une image à partager"))
        self.recap_button.setCursor(Qt.PointingHandCursor)
        self.recap_button.clicked.connect(self._open_recap)
        head.addWidget(self.recap_button)
        self.open_button = QPushButton(tr("Ouvrir la série"))
        self.open_button.setCursor(Qt.PointingHandCursor)
        self.open_button.clicked.connect(self._open_series)
        self.open_button.hide()
        head.addWidget(self.open_button)
        # fermeture aussi dans la fenetre, a cote des autres boutons
        self.close_button = QPushButton(tr("Fermer"))
        self.close_button.setToolTip(tr("Fermer les statistiques (Échap)"))
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.clicked.connect(self.accept)
        head.addWidget(self.close_button)
        v.addLayout(head)

        row = QHBoxLayout()
        self.caption = QLabel()
        self.caption.setObjectName("caption")
        self.caption.setTextFormat(Qt.PlainText)
        row.addWidget(self.caption, 1)
        # la methode s'affiche en infobulle (survol ou clic) : elle ne prend
        # aucune place a l'ecran
        self.method = _tip_button(tr("Méthode de mesure"), "<qt>" + tr(
            "Une page compte comme lue après {dwell} s d'affichage (feuilleter ne "
            "compte pas) ; le temps de lecture ignore les pauses de plus de {pause} s. "
            "Un tome est terminé quand sa dernière page est atteinte dans le lecteur : "
            "« Marquer comme lu » ne compte pas comme une lecture.",
            dwell=f"{MIN_DWELL:.0f}", pause=f"{PAUSE_CAP:.0f}") + "</qt>", self)
        row.addWidget(self.method)
        v.addLayout(row)
        return v

    def _open_recap(self):
        RecapDialog(self.store.reading_log, self.c, self.today, self.resolve, self).exec()

    def _build_body(self):
        c, dc = self.c, self.dc
        body = self.body_layout

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
        body.addWidget(self.empty_card, 1)

        # --- chiffres cles
        self.pages_spark = Sparkline(dc["activity"], c)
        self.days_meter = Meter(dc["activity"])
        self.tiles = [StatTile(tr("Temps de lecture"), hero=True),
                      StatTile(tr("Pages lues"), self.pages_spark),
                      StatTile(tr("Tomes terminés")),
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
        body.addWidget(self.tiles_host)

        # --- premiere rangee : le temps de lecture et les series
        self.time_chart = BarChart(dc["activity"], c, ticks=stats.time_ticks,
                                   value_fmt=lambda s: stats.fmt_duration(s, compact=True),
                                   empty_text=tr("Aucune lecture enregistrée sur la période."))
        self.time_card = ChartCard(tr("Temps de lecture"), self.time_chart,
                                   [tr("Jour"), tr("Temps"), tr("Pages"), tr("Tomes terminés")])
        self.series_list = HBarList(dc["activity"], c, tr("Aucune lecture enregistrée sur la période."),
                                    scale=1.0)
        self.series_list.activated.connect(self._series_activated)
        self.series_card = ChartCard(tr("Séries les plus lues"), self.series_list)
        self.series_card.set_subtitle(tr("Part du temps de lecture"))
        self.detail = QWidget()
        row = QHBoxLayout(self.detail)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(self.time_card, 3)
        row.addWidget(self.series_card, 1)
        body.addWidget(self.detail, 1)

        # --- seconde rangee : regularite, tomes termines, bibliotheque
        self.calendar = CalendarHeatmap(dc["activity"], c)
        self.weekdays = BarChart(dc["activity"], c, ticks=stats.time_ticks,
                                 value_fmt=lambda s: stats.fmt_duration(s, compact=True),
                                 empty_text=tr("Aucune lecture enregistrée sur la période."))
        regularity = QWidget()
        rv = QVBoxLayout(regularity)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.calendar)
        rv.addWidget(self.weekdays)
        regularity.setMinimumHeight(self.calendar.minimumHeight())
        self.calendar_card = ChartCard(tr("Régularité"), regularity)
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
        body.addWidget(self.habits, 1)

    def _library_card(self):
        """Etat actuel de la bibliotheque : il ne depend pas de la periode,
        et la carte le dit. Le temps restant tient en un chiffre et une
        ligne ; le detail du calcul est dans l'infobulle (i)."""
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
        value, short, detail = self._backlog()
        self.backlog_value = QLabel(value)
        self.backlog_value.setObjectName("backlogValue")
        self.backlog_value.setVisible(bool(value))
        line = QHBoxLayout()
        line.setSpacing(6)
        self.backlog_detail = QLabel(short)
        self.backlog_detail.setObjectName("cardSub")
        self.backlog_detail.setWordWrap(True)
        self.backlog_info = _tip_button("ⓘ", detail, self)
        self.backlog_info.setAccessibleName(tr("Détail du calcul"))
        self.backlog_info.setVisible(bool(detail))
        line.addWidget(self.backlog_detail, 1)
        line.addWidget(self.backlog_info, 0, Qt.AlignTop)
        v.addWidget(label)
        v.addWidget(self.backlog_value)
        v.addLayout(line)
        v.addStretch(1)
        card = ChartCard(tr("Bibliothèque"), body)
        card.set_subtitle((trn(total, "{n} tome", "{n} tomes") if total else tr("Vide"))
                          + " · " + tr("indépendant de la période"))
        return card

    def _backlog(self) -> tuple:
        """(chiffre, ligne, detail du calcul) du temps qu'il reste a lire
        dans la bibliotheque, au rythme habituel."""
        pace = self.store.reading_pace()
        remaining = self.library.get("remaining_pages", 0)
        if not pace:
            return "", (tr("Rythme de lecture pas encore mesuré : l'estimation s'affichera "
                           "après quelques pages lues.")), ""
        if not remaining:
            return "", tr("Rien en attente. Votre rythme : {pace}.", pace=fmt_pace(pace)), ""
        # chaque tome restant est compte au rythme de sa serie quand elle a
        # assez ete lue (contemplative ou bavarde), sinon au rythme moyen
        seconds, own_pages = remaining * pace, 0
        by_volume = self.library.get("remaining_by_volume")
        if by_volume and self.resolve is not None:
            paces = stats.series_paces(self.store.volume_paces(), self.resolve)
            seconds = 0.0
            for volume, pages in by_volume.items():
                found = self.resolve(volume)
                own = paces.get(found[0]) if found else None
                seconds += pages * (own or pace)
                own_pages += pages if own else 0
        if own_pages:
            detail = trn(remaining, "{n} page, au rythme de chaque série (moyenne : {pace})",
                         "{n} pages, au rythme de chaque série (moyenne : {pace})",
                         pace=fmt_pace(pace))
        else:
            detail = trn(remaining, "{n} page à votre rythme de {pace}",
                         "{n} pages à votre rythme de {pace}", pace=fmt_pace(pace))
        unknown = self.library.get("unknown_pages", 0)
        if unknown:
            detail += trn(unknown, ", hors {n} tome au nombre de pages inconnu",
                          ", hors {n} tomes au nombre de pages inconnu")
        unread, reading = self.library.get("unread", 0), self.library.get("reading", 0)
        short = [trn(unread, "{n} tome non lu", "{n} tomes non lus")] if unread else []
        if reading:
            short.append(trn(reading, "{n} en cours", "{n} en cours"))
        if len(short) == 2:
            short = [tr("{first} et {second}", first=short[0], second=short[1])]
        return f"≈ {fmt_estimate(seconds)}", "".join(short), detail + "."

    # ------------------------------------------------------------ defilement
    def _update_more(self):
        """Lien « plus bas » : seulement sur la vue generale, tant qu'une
        partie de son contenu est sous le bord de l'ecran."""
        bar = self.scroll.verticalScrollBar()
        self.more.setVisible(self.series_key is None and bar.maximum() > 0
                             and bar.value() < bar.maximum() - 8)

    def showEvent(self, event):
        super().showEvent(event)
        self._update_more()

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

    # ------------------------------------------------------------ vue d'une serie
    def _series_holdings(self, key):
        if self.holdings is None or not key:
            return None
        if key not in self._holdings_cache:
            self._holdings_cache[key] = self.holdings(key)
        return self._holdings_cache[key]

    def _series_activated(self, index):
        self.show_series(self.report.series[index].key)

    def show_series(self, key):
        """Affiche les statistiques de la serie `key` a la place de la vue
        generale. Sans effet pour une serie absente de la bibliotheque."""
        holdings = self._series_holdings(key)
        if holdings is None:
            return
        report = series_stats.build_series_report(
            self.store.reading_log, holdings, self.today, self.resolve,
            library_pace=self.store.reading_pace(), owner=self.owner)
        self.series_key = key
        self.series_view.set_report(report, self.today)
        self.pages.setCurrentIndex(1)
        self.pages.currentWidget().verticalScrollBar().setValue(0)
        self.title.setText(holdings.name)
        self.caption.setText(self.series_view.caption())
        for w in (self.crumb, self.crumb_sep):
            w.show()
        self.segmented.hide()
        self.recap_button.hide()
        self.open_button.setVisible(self.open_series is not None)
        self._update_more()

    def show_overview(self):
        self.series_key = None
        self.pages.setCurrentIndex(0)
        self.title.setText(tr("Statistiques de lecture"))
        self.caption.setText(_caption(self.report))
        for w in (self.crumb, self.crumb_sep, self.open_button):
            w.hide()
        self.segmented.show()
        self.recap_button.show()
        self._update_more()

    def _open_series(self):
        key = self.series_key
        self.accept()
        if key is not None and self.open_series is not None:
            self.open_series(key)

    def reject(self):
        # Echap dans la vue d'une serie : retour a la vue generale
        if self.series_key is not None:
            self.show_overview()
            return
        super().reject()

    # ------------------------------------------------------------ mise a jour
    def _refresh(self, report):
        empty = report.first_day is None
        self.empty_card.setVisible(empty)
        for block in (self.tiles_host, self.detail, self.calendar_card, self.finished_card):
            block.setVisible(not empty)
        if self.series_key is None:
            self.caption.setText(_caption(report))
        self._refresh_tiles(report)
        self._refresh_time(report)
        self._refresh_series(report)
        self._refresh_calendar(report)
        self._refresh_finished(report)

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

        # tomes seuls ; les chapitres termines et le dernier tome en sous-titre
        # (une mini-tendance de fins de tome, evenements rares, restait vide)
        volumes = t.finished - t.finished_chapters
        delta, tip = _delta(volumes, prev and prev.finished - prev.finished_chapters, _fmt_int,
                            lambda n: trn(n, "{n} tome", "{n} tomes"), report, report.first_day)
        sub = [trn(t.finished_chapters, "+ {n} chapitre", "+ {n} chapitres")] \
            if t.finished_chapters else []
        last = next(((self._finished_name(volume, title, series), day)
                     for day, volume, title, series in report.finished_volumes
                     if self._finished_name(volume, title, series)), None)
        if last is not None:
            sub.append(tr("Dernier : {title}, {day}", title=last[0],
                          day=fmt_day(last[1], year=last[1].year != self.today.year)))
        finished.set_content(_fmt_int(volumes), delta, " · ".join(sub), tip)

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
        rows = [(s.name, s.share,
                 (stats.fmt_duration(s.seconds, compact=True) if timed
                  else trn(s.pages, "{n} page", "{n} pages"))
                 + " · " + tr("{n} %", n=round(100 * s.share)))
                for s in report.series]
        clickable = [i for i, s in enumerate(report.series) if self._series_holdings(s.key)]
        self.series_list.set_rows(rows, clickable)
        self.series_card.set_subtitle(tr("Part du temps de lecture · cliquez pour le détail")
                                      if clickable else tr("Part du temps de lecture"))

    def _refresh_calendar(self, report):
        streak = (trn(report.streak, "Série en cours : {n} jour", "Série en cours : {n} jours")
                  if report.streak else tr("Pas de série en cours"))
        if report.best_streak > report.streak:
            streak += " · " + trn(report.best_streak, "record : {n} jour", "record : {n} jours")
        self.calendar.set_days(report.calendar)
        short = report.period.key in SHORT_PERIODS
        self.calendar.setVisible(not short)
        self.weekdays.setVisible(short)
        if short:
            # sur 7 ou 30 jours, le calendrier repeterait l'histogramme
            averages = stats.weekday_averages(report.buckets)
            self.weekdays.set_bars(
                (day_name(i), avg, f"{stats.fmt_duration(avg)}\n"
                 + tr("en moyenne le {day}", day=tr(stats.WEEKDAYS_FR[i])) + " · "
                 + trn(n, "sur {n} semaine", "sur {n} semaines"))
                for i, (avg, n) in enumerate(averages))
            self.calendar_card.set_title(tr("Jours de lecture préférés"))
            self.calendar_card.set_subtitle(tr("Temps moyen par jour de la semaine") + " · " + streak)
            return
        self.calendar_card.set_title(tr("Régularité"))
        if report.calendar and report.calendar[0].start > report.period.start:
            streak += " · " + tr("53 dernières semaines affichées")
        self.calendar_card.set_subtitle(streak)

    def _finished_name(self, volume, title, series) -> str:
        """Nom d'un tome termine : son titre actuel dans la bibliotheque,
        sinon celui note au moment de la lecture, ou "" s'il est perdu."""
        name = self.titles.get(volume) or title or series
        if not name and not volume.startswith("c1:"):
            # ancienne entree indexee par chemin, peut-etre venue d'un autre
            # systeme (sauvegarde importee) : PureWindowsPath coupe sur \ et /
            name = PureWindowsPath(volume).stem
        return name

    def _refresh_finished(self, report):
        items, unknown = [], {}   # unknown : jour -> position de sa ligne « tomes absents »
        for day, volume, title, series in report.finished_volumes:
            date = fmt_day(day, year=day.year != self.today.year)
            name = self._finished_name(volume, title, series)
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
