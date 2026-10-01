"""Journal de lecture : table SQLite et requetes des statistiques.

Contrairement aux autres depots (dictionnaires JSON charges en memoire, voir
database.py), le journal est une vraie table, jamais chargee au demarrage :

    reading_log(day, device, volume, pages, seconds, sessions, finished,
                title, series)      cle primaire (day, device, volume)

* une seance n'ecrit qu'UNE ligne (ajout aux compteurs du jour, pour ce
  tome, sur cet appareil), dans une transaction ;
* les statistiques sont des agregats SQL bornes a une periode. La cle
  primaire commence par le jour : une periode est un simple parcours
  d'intervalle de la table, sans index supplementaire ;
* chaque appareil n'ecrit que ses propres lignes, et l'import d'une
  sauvegarde remplace en bloc les lignes d'un AUTRE appareil : importer deux
  fois le meme fichier ne compte rien en double (voir backup.py).

Les calculs sur ces agregats (periodes, comparaison, series de jours,
classement) sont dans core/stats.py, purs.
"""

import datetime as _dt
import json
import logging

from beheread.core import stats

# etapes de la migration vers le schema 2 (voir database.MIGRATIONS)
SCHEMA = [
    """CREATE TABLE reading_log (
           day TEXT NOT NULL, device TEXT NOT NULL, volume TEXT NOT NULL,
           pages INTEGER NOT NULL DEFAULT 0, seconds REAL NOT NULL DEFAULT 0,
           sessions INTEGER NOT NULL DEFAULT 0, finished INTEGER NOT NULL DEFAULT 0,
           title TEXT NOT NULL DEFAULT '', series TEXT NOT NULL DEFAULT '',
           PRIMARY KEY (day, device, volume)) WITHOUT ROWID""",
    """CREATE TABLE reading_devices (
           device TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
           updated REAL NOT NULL DEFAULT 0)""",
]

_ADD = """INSERT INTO reading_log(day, device, volume, pages, seconds, sessions, finished,
                                  title, series)
          VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(day, device, volume) DO UPDATE SET
              pages = pages + excluded.pages, seconds = seconds + excluded.seconds,
              sessions = sessions + excluded.sessions,
              finished = finished + excluded.finished,
              title = excluded.title, series = excluded.series"""
_TOUCH = """INSERT INTO reading_devices(device, name, updated) VALUES(?, ?, ?)
            ON CONFLICT(device) DO UPDATE SET name = excluded.name, updated = excluded.updated"""


def _replace_device(cur, device, section):
    """Remplace toutes les lignes d'un appareil par celles d'une section au
    format d'echange (voir stats.journal_rows)."""
    cur.execute("DELETE FROM reading_log WHERE device = ?", (device,))
    cur.executemany(_ADD, list(stats.journal_rows(device, section)))
    try:
        updated = float(section.get("updated") or 0)
    except (TypeError, ValueError):
        updated = 0.0
    cur.execute(_TOUCH, (device, str(section.get("name") or ""), updated))


def copy_legacy_journal(cur):
    """Migration vers le schema 2 : reprend l'ancien journal (table
    stats_devices, une ligne JSON par appareil avec tout son historique). La
    table d'origine est laissee intacte."""
    for device, text in cur.execute("SELECT key, value FROM stats_devices").fetchall():
        try:
            section = json.loads(text)
        except ValueError:
            logging.warning("Ancien journal illisible ignore : appareil %r", device)
            continue
        if isinstance(section, dict):
            _replace_device(cur, device, section)


def _iso(date):
    return date.isoformat() if isinstance(date, _dt.date) else date


class ReadingLog:
    def __init__(self, db):
        self.db = db

    def _query(self, sql, params=()):
        with self.db.lock:
            return self.db.conn.execute(sql, params).fetchall()

    # ------------------------------------------------------------ ecriture
    def add(self, device, name, day, volume, pages, seconds, finished, title, series, now,
            cur=None):
        """Ajoute une seance (ou une fin de tome seule) aux compteurs du jour.
        Avec `cur`, l'ecriture rejoint la transaction de l'appelant."""
        pages, seconds = max(0, int(pages)), round(max(0.0, float(seconds)), 1)
        row = (_iso(day), device, volume, pages, seconds, 1 if (pages or seconds) else 0,
               1 if finished else 0, title or "", series or "")
        if cur is not None:
            cur.execute(_ADD, row)
            cur.execute(_TOUCH, (device, name, now))
            return
        with self.db.transaction() as cur:
            self.add(device, name, day, volume, pages, seconds, finished, title, series, now, cur)

    # ------------------------------------------------------------ agregats par periode
    def first_day(self, sessions_only=False):
        """Premier jour du journal, tous appareils confondus, ou None.
        `sessions_only` : premier jour avec une seance de lecture - les fins
        de tome reprises d'avant le journal n'ont ni pages ni temps."""
        where = " WHERE sessions > 0" if sessions_only else ""
        day = self._query("SELECT MIN(day) FROM reading_log" + where)[0][0]
        return _dt.date.fromisoformat(day) if day else None

    def totals(self, start, end) -> stats.Totals:
        row = self._query(
            """SELECT COALESCE(SUM(pages), 0), COALESCE(SUM(seconds), 0.0),
                      COALESCE(SUM(sessions), 0), COALESCE(SUM(finished), 0),
                      COUNT(DISTINCT CASE WHEN pages > 0 THEN day END),
                      COUNT(DISTINCT CASE WHEN pages > 0 THEN volume END)
               FROM reading_log WHERE day BETWEEN ? AND ?""", (_iso(start), _iso(end)))[0]
        return stats.Totals(*row)

    def buckets(self, start, end, grain="day"):
        """[(cle, pages, secondes, fins)] par jour (« AAAA-MM-JJ ») ou par
        mois (« AAAA-MM ») ; seuls les jours ou mois avec une ligne y figurent."""
        key = "substr(day, 1, 7)" if grain == "month" else "day"
        return self._query(
            f"""SELECT {key} AS bucket, SUM(pages), SUM(seconds), SUM(finished)
                FROM reading_log WHERE day BETWEEN ? AND ?
                GROUP BY bucket ORDER BY bucket""", (_iso(start), _iso(end)))

    def volumes(self, start, end):
        """[(tome, titre, serie, pages, secondes, fins)] par tome, du plus
        recemment lu au plus ancien. Titre et serie sont ceux de la ligne la
        plus recente (propriete de SQLite : avec un unique MAX(), les
        colonnes hors agregat viennent de la ligne qui porte ce maximum)."""
        return [row[:6] for row in self._query(
            """SELECT volume, title, series, SUM(pages), SUM(seconds), SUM(finished), MAX(day)
               FROM reading_log WHERE day BETWEEN ? AND ?
               GROUP BY volume ORDER BY MAX(day) DESC, volume""", (_iso(start), _iso(end)))]

    def finished(self, start, end, limit):
        """[(jour, tome, titre, serie)] des dernieres fins de tome de la
        periode, de la plus recente a la plus ancienne."""
        return self._query(
            """SELECT day, volume, title, series FROM reading_log
               WHERE finished > 0 AND day BETWEEN ? AND ?
               ORDER BY day DESC, volume LIMIT ?""", (_iso(start), _iso(end), int(limit)))

    def active_days(self):
        """Jours (« AAAA-MM-JJ ») ou au moins une page a ete lue, pour les
        series de jours consecutifs (sur tout l'historique)."""
        return [row[0] for row in self._query(
            "SELECT DISTINCT day FROM reading_log WHERE pages > 0 ORDER BY day")]

    # ------------------------------------------------------------ sauvegarde
    def devices(self) -> dict:
        """{appareil: date de derniere ecriture} des sections connues."""
        return dict(self._query("SELECT device, updated FROM reading_devices"))

    def export(self) -> dict:
        """Tout le journal au format d'echange (voir stats.py)."""
        rows = {}
        for device, *row in self._query(
                """SELECT device, day, volume, pages, seconds, sessions, finished, title, series
                   FROM reading_log ORDER BY device, day"""):
            rows.setdefault(device, []).append(row)
        return {"devices": {
            device: stats.journal_section(name, updated, rows.get(device, ()))
            for device, name, updated in self._query(
                "SELECT device, name, updated FROM reading_devices")}}

    def replace_devices(self, sections: dict, cur=None):
        """Remplace les lignes des appareils donnes ({appareil: section au
        format d'echange}). Avec `cur`, dans la transaction de l'appelant."""
        if not sections:
            return
        if cur is None:
            with self.db.transaction() as cur:
                self.replace_devices(sections, cur)
            return
        for device, section in sections.items():
            _replace_device(cur, device, section)
