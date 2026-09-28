"""Base de donnees locale (SQLite) : schema versionne et depots de donnees.

Chaque depot (reglages, progression, metadonnees, empreintes, statistiques)
est une table `cle -> valeur JSON`, chargee en memoire au demarrage (lectures
instantanees depuis l'interface) et ecrite de facon INCREMENTALE : seules les
lignes modifiees depuis la derniere ecriture sont reecrites, dans une
transaction. C'est plus robuste (une ecriture est atomique, meme en cas de
coupure) et bien moins couteux que de reecrire des fichiers JSON entiers a
chaque sauvegarde.

Le schema est versionne (PRAGMA user_version) ; chaque evolution ajoute une
etape dans MIGRATIONS, appliquee une seule fois, dans une transaction.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

TABLES = ("settings", "progress", "volume_meta", "series_meta", "fingerprints",
          "stats_devices", "library_index")

# version -> instructions SQL qui y menent depuis la precedente
MIGRATIONS = {
    1: [f"CREATE TABLE {t} (key TEXT PRIMARY KEY, value TEXT NOT NULL)" for t in TABLES]
       # informations sur la base elle-meme (ex. import des anciens JSON termine)
       + ["CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"],
}


class DatabaseError(Exception):
    pass


class DatabaseTooNew(DatabaseError):
    """La base a ete creee par une version plus recente de Beheread."""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        # une seule connexion, partagee sous verrou (thread UI au demarrage,
        # thread de sauvegarde ensuite)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False,
                                    isolation_level=None, timeout=10)
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
        self.migrate()

    @property
    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self):
        current = self.version
        if current > SCHEMA_VERSION:
            raise DatabaseTooNew(
                f"Base de donnees en version {current}, cette version de Beheread "
                f"ne connait que la version {SCHEMA_VERSION}.")
        for version in range(current + 1, SCHEMA_VERSION + 1):
            with self.transaction() as cur:
                for sql in MIGRATIONS[version]:
                    cur.execute(sql)
                cur.execute(f"PRAGMA user_version = {version}")
            logging.info("Schema de la base migre en version %d", version)

    def get_meta(self, key):
        with self.lock:
            row = self.conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def set_meta(cur, key, value):
        """A appeler dans une transaction (atomique avec les donnees)."""
        cur.execute("INSERT INTO app_meta(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    @contextmanager
    def transaction(self):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                yield cur
            except BaseException:
                cur.execute("ROLLBACK")
                raise
            cur.execute("COMMIT")

    def close(self):
        with self.lock:
            self.conn.close()


class JsonTable:
    """Depot : un dictionnaire en memoire (cle -> valeur JSON) persiste dans
    une table. `data` est le dictionnaire vivant, partage avec le reste de
    l'application ; `pending_changes` calcule ce qui differe de la derniere
    ecriture, `write` l'enregistre."""

    def __init__(self, table: str):
        if table not in TABLES:
            raise ValueError(table)
        self.table = table
        self.data = {}
        self._persisted = {}   # cle -> texte JSON tel qu'il est en base

    def load(self, db: Database):
        with db.lock:
            rows = db.conn.execute(f"SELECT key, value FROM {self.table}").fetchall()
        for key, text in rows:
            try:
                self.data[key] = json.loads(text)
            except ValueError:
                logging.warning("Ligne illisible ignoree dans %s : %r", self.table, key)
                continue
            self._persisted[key] = text

    def pending_changes(self):
        """(lignes a ecrire, cles a supprimer) depuis la derniere ecriture.
        Peut lever RuntimeError si le dictionnaire est modifie par un autre
        thread pendant le calcul (l'appelant retente)."""
        upserts = []
        for key, value in self.data.items():
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if self._persisted.get(key) != text:
                upserts.append((key, text))
        deletes = [k for k in self._persisted if k not in self.data]
        return upserts, deletes

    def write(self, cur, upserts, deletes):
        if upserts:
            cur.executemany(f"INSERT INTO {self.table}(key, value) VALUES(?, ?) "
                            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", upserts)
        if deletes:
            cur.executemany(f"DELETE FROM {self.table} WHERE key = ?", [(k,) for k in deletes])

    def mark_written(self, upserts, deletes):
        for key, text in upserts:
            self._persisted[key] = text
        for key in deletes:
            self._persisted.pop(key, None)
