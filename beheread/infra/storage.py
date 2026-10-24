"""Persistance locale : dossiers de la bibliotheque, progression de lecture,
cache des metadonnees et des vignettes. Tout est stocke dans le dossier de
donnees de l'utilisateur : %APPDATA%/MangaReaderPy sous Windows,
~/Library/Application Support/Beheread sous macOS (voir beheread.platforms).
Aucune connexion reseau.

Trois points d'architecture :

* Base SQLite versionnee (beheread.db, voir database.py) : un depot par type
  de donnee, charge en memoire au demarrage et ecrit de facon incrementale et
  transactionnelle. Les anciens fichiers JSON (versions <= 0.1) sont importes
  automatiquement au premier lancement, puis ranges dans legacy-json/. Le
  journal de lecture (statistiques) est une table a part, interrogee en SQL
  et jamais chargee en memoire (voir reading_log.py).

* Identite par contenu. La progression et les metadonnees sont indexees par
  une empreinte du contenu du fichier (taille + debut du fichier), pas par
  son chemin absolu. Renommer ou deplacer un tome conserve donc sa
  progression, et deux copies identiques la partagent. Les anciennes entrees
  indexees par chemin sont migrees a la volee au premier acces.

* Ecritures differees. Les sauvegardes sont regroupees (debounce) puis
  ecrites par un minuteur d'arriere-plan, pour ne pas ecrire le disque a
  chaque tour de page ou a chaque pixel de la barre de defilement. Les
  operations rares et importantes (ajout/retrait de dossier, suppression)
  forcent une ecriture immediate. `flush()` doit etre appele a la fermeture
  de l'application pour garantir la persistance des dernieres modifications.
"""

import csv
import datetime
import hashlib
import json
import logging
import os
import platform
import threading
import time
import uuid
from pathlib import Path

from beheread import platforms
from beheread.config import THUMB_SCALE
from beheread.core import backup as backup_model
from beheread.core import stats as stats_model
from beheread.core import units
from beheread.i18n import fmt_decimal, language, tr
from beheread.infra import mangadex, secret_store
from beheread.infra.database import Database, JsonTable
from beheread.infra.reading_log import ReadingLog

SAVE_DELAY = 0.6          # secondes d'inactivite avant une ecriture differee
# taille maximale d'un fichier importe comme sauvegarde : tres au-dessus d'une
# vraie sauvegarde (quelques Mo pour des milliers de tomes et des annees de
# journal de lecture)
MAX_BACKUP_BYTES = 64 * 1024 * 1024
DB_NAME = "beheread.db"

# depot -> table SQLite (voir database.py)
REPOS = {"settings": "settings", "progress": "progress", "volume_meta": "volume_meta",
         "series_meta": "series_meta", "fp": "fingerprints", "index": "library_index",
         # schema 3 : une ligne par tome (ou par serie) au lieu d'un dictionnaire
         # entier dans la ligne « settings »
         "added": "volume_added", "pages": "page_counts", "overrides": "series_overrides",
         "directions": "volume_directions", "dismissed": "continue_dismissed",
         "al_map": "anilist_map", "al_pending": "anilist_pending", "al_last": "anilist_last",
         "entries": "library_entries"}
# nom passe a _schedule -> depots a ecrire (par defaut : le depot du meme nom)
DIRTY_TO_REPOS = {"meta": ("volume_meta", "series_meta")}
REPO_TO_DIRTY = {"volume_meta": "meta", "series_meta": "meta"}
REPO_TO_DIRTY.update({table: name for name, table in REPOS.items()
                      if table not in REPO_TO_DIRTY})
# reglages autrefois ranges dans la ligne « settings » -> depot du schema 3
SPLIT_SETTINGS = {"added": "added", "pages": "pages", "series_overrides": "overrides",
                  "volume_direction": "directions", "continue_dismissed": "dismissed"}
SPLIT_ANILIST = {"map": "al_map", "pending": "al_pending", "last": "al_last"}
# anciens fichiers JSON (versions <= 0.1), importes au premier lancement
LEGACY_IMPORT_KEY = "legacy_json_import"
# fins de tome anterieures au journal de lecture, reprises une seule fois
FINISHED_HISTORY_KEY = "finished_history_import"
LEGACY_FILES = {"settings": "settings.json", "progress": "progress.json",
                "meta": "meta_cache.json", "fp": "fingerprints.json",
                "stats": "stats.json", "index": "library_index.json"}


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _index_rows(entries) -> dict:
    """Index de bibliotheque (liste d'entrees) -> {chemin: entree + rang} :
    une ligne par tome, l'ordre etant garde par le rang (« seq »)."""
    rows = {}
    for i, entry in enumerate(entries if isinstance(entries, list) else []):
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            rows[entry["path"]] = dict(entry, seq=i)
    return rows
FP_HEAD = 65536           # octets de tete lus pour l'empreinte de contenu


def is_cloud_placeholder(path) -> bool:
    """True si le fichier est un espace reserve cloud non telecharge (iCloud
    Drive / OneDrive "libere de l'espace") : son contenu n'est pas en local et
    la moindre lecture (meme 1 octet) declencherait son telechargement complet
    et bloquant. Base uniquement sur os.stat, sans jamais ouvrir le fichier."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    return platforms.is_cloud_placeholder(st)


def is_cloud_stat(st) -> bool:
    """Meme test, sur un stat deja obtenu (scan des dossiers)."""
    return platforms.is_cloud_placeholder(st)


def _unlink_patiently(path: Path):
    """Supprime un fichier de cache que Windows tient parfois un instant
    (vignette en cours de lecture, antivirus) : quelques essais, puis il est
    laisse en place (sans consequence : il sera reecrit)."""
    for attempt in range(10):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError:
            if attempt == 9:
                logging.info("Fichier de cache non supprime : %s", path, exc_info=True)
            else:
                time.sleep(0.05)


def data_dir() -> Path:
    d = platforms.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _compute_fingerprint(path: str) -> str:
    """Empreinte de contenu : taille du fichier + ses premiers Ko. Suffisant
    pour distinguer deux tomes differents, stable au deplacement/renommage."""
    st = os.stat(path)
    h = hashlib.sha1()
    h.update(str(st.st_size).encode("ascii"))
    with open(path, "rb") as f:
        h.update(f.read(FP_HEAD))
    return "c1:" + h.hexdigest()


class Store:
    """Regroupe les parametres, la progression et les caches de metadonnees,
    avec identite par contenu et ecritures differees."""

    # valeur d'override signifiant "detache de tout regroupement de serie"
    SERIES_DETACHED = "\x00__detached__"

    def __init__(self):
        self.dir = data_dir()
        self.thumb_dir = self.dir / "thumbnails"
        self.thumb_dir.mkdir(exist_ok=True)
        self.cover_dir = self.dir / "covers"      # images choisies comme couverture

        # base SQLite : un depot (table cle -> JSON) par type de donnee
        self.db = Database(self.dir / DB_NAME)
        self._repos = {name: JsonTable(table) for name, table in REPOS.items()}
        for repo in self._repos.values():
            repo.load(self.db)

        # vues « dictionnaire » utilisees par le reste de l'application : ce
        # sont les dictionnaires vivants des depots (memes objets)
        self.settings = self._repos["settings"].data
        self.progress = self._repos["progress"].data
        self.meta_cache = {"volume": self._repos["volume_meta"].data,
                           "series": self._repos["series_meta"].data}
        self._fp = self._repos["fp"].data                 # chemin -> {m, s, k}
        # donnees par tome (empreinte -> valeur), une ligne chacune
        self._added = self._repos["added"].data           # date d'ajout
        self._pages = self._repos["pages"].data           # nombre de pages
        self._overrides = self._repos["overrides"].data   # regroupement manuel
        self._directions = self._repos["directions"].data  # sens de lecture d'un tome seul
        self._dismissed = self._repos["dismissed"].data   # masques de « Continuer »
        # journal de lecture (statistiques) : table SQL, voir reading_log.py
        self.reading_log = ReadingLog(self.db)
        # empreintes deja resolues pendant la session (chemin -> cle) : evite un
        # os.stat a CHAQUE appel de key_for, appele plusieurs fois par item a
        # chaque reconstruction de la liste et a chaque frappe de recherche
        # (couteux sur disque reseau). Invalide a chaque scan (voir
        # invalidate_key_memo), qui revalide les empreintes par mtime+taille.
        self._key_memo = {}

        # ecritures differees : un seul thread de sauvegarde pour toute la
        # session, reveille par _schedule (plutot qu'un threading.Timer cree a
        # chaque tour de page)
        self._save_lock = threading.RLock()
        self._io_lock = threading.Lock()   # serialise les ecritures disque
        self._dirty = set()
        # nom -> cles modifiees depuis la derniere ecriture (seules celles-ci
        # sont serialisees), ou None : tout le depot est a comparer
        self._dirty_keys = {}
        self._deadline = None              # echeance de la prochaine ecriture (monotonic)
        self._wake = threading.Event()
        self._saver = None
        self._closed = False

        if self.db.get_meta(LEGACY_IMPORT_KEY) is None:
            self._import_legacy_json()
        self._split_settings()
        self.settings.setdefault("folders", [])
        self.settings.setdefault("reader", {})
        self._migrate_meta_cache_out_of_settings()
        # ancien rythme de lecture : il mesurait l'intervalle entre deux tours
        # de page, feuilletage compris, et non des secondes par page lue. Sans
        # rapport avec la mesure actuelle, il est oublie puis re-mesure.
        # Puis rythme lisse (moyenne mobile des medianes de chaque seance) :
        # remplace par un calcul sur le journal de lecture (reading_pace).
        stale = [self.settings["reader"].pop(k, None)
                 for k in ("median_page_seconds", "page_seconds")]
        if any(v is not None for v in stale):
            self._schedule("settings")
        if self.db.get_meta(FINISHED_HISTORY_KEY) is None:
            self._import_finished_history()

    # ------------------------------------------------------------ schema 3
    def _split_settings(self):
        """Deplace dans leurs depots du schema 3 les donnees par tome et
        l'etat AniList encore ranges dans la ligne « settings » (base d'avant
        le schema 3, ou anciens fichiers JSON tout juste importes), ainsi que
        l'index de la bibliotheque (un seul bloc -> une ligne par tome). Une
        seule transaction : rien n'est perdu si elle echoue, elle est alors
        retentee au lancement suivant."""
        moved = set()
        for old, name in SPLIT_SETTINGS.items():
            values = self.settings.pop(old, None)
            if values is None:
                continue
            moved.update(("settings", name))
            if isinstance(values, dict):
                for key, value in values.items():
                    self._repos[name].data.setdefault(key, value)
        anilist = self.settings.get("anilist")
        if isinstance(anilist, dict):
            for old, name in SPLIT_ANILIST.items():
                values = anilist.pop(old, None)
                if values is None:
                    continue
                moved.update(("settings", name))
                if isinstance(values, dict):
                    for key, value in values.items():
                        self._repos[name].data.setdefault(key, value)
        index = self._repos["index"].data.pop("entries", None)
        if index is not None:
            moved.update(("index", "entries"))
            self._repos["entries"].data.update(_index_rows(index))
        if not moved:
            return
        try:
            with self._io_lock:
                self._write_all(sorted(moved))
        except Exception:
            logging.error("Passage des donnees au schema 3 impossible (nouvel essai "
                          "au prochain lancement)", exc_info=True)
            raise
        logging.info("Donnees deplacees vers les tables du schema 3 : %s",
                     ", ".join(sorted(moved)))

    # ------------------------------------------------------------ import des anciens JSON
    def _import_legacy_json(self):
        """Premier lancement sur SQLite : reprend les donnees des anciens
        fichiers JSON, les ecrit en base avec un marqueur « import termine »
        (une seule transaction), puis range les fichiers dans legacy-json/
        (sauvegarde, jamais relue).

        Tant que le marqueur est absent (import jamais tente, ou interrompu par
        une erreur), l'import est retente au lancement suivant. Une fois pose,
        plus jamais : un ancien fichier reste en place (s'il n'a pas pu etre
        range) n'ecrasera donc jamais des donnees plus recentes."""
        found = [f for f in LEGACY_FILES.values() if (self.dir / f).exists()]
        if not found:
            with self.db.transaction() as cur:
                Database.set_meta(cur, LEGACY_IMPORT_KEY, "aucun fichier")
            return
        settings = self._load(self.dir / LEGACY_FILES["settings"], {})
        meta = self._load(self.dir / LEGACY_FILES["meta"], {})
        stats = self._load(self.dir / LEGACY_FILES["stats"], {})
        index = self._load(self.dir / LEGACY_FILES["index"], [])
        for key, value in (settings if isinstance(settings, dict) else {}).items():
            self.settings[key] = value
        self.progress.update(_as_dict(self._load(self.dir / LEGACY_FILES["progress"], {})))
        if isinstance(meta, dict):
            self.meta_cache["volume"].update(_as_dict(meta.get("volume")))
            self.meta_cache["series"].update(_as_dict(meta.get("series")))
        self._fp.update(_as_dict(self._load(self.dir / LEGACY_FILES["fp"], {})))
        journal = {k: v for k, v in _as_dict(_as_dict(stats).get("devices")).items()
                   if isinstance(v, dict)}
        if isinstance(index, list):
            self._repos["index"].data["entries"] = index
        try:
            self._write_all(list(self._repos),
                            meta={LEGACY_IMPORT_KEY: f"{len(found)} fichier(s) le {time.ctime()}"},
                            extra=lambda cur: self.reading_log.replace_devices(journal, cur))
        except Exception:
            logging.error("Import des anciens fichiers JSON impossible (nouvel essai "
                          "au prochain lancement)", exc_info=True)
            raise
        backup = self.dir / "legacy-json"
        backup.mkdir(exist_ok=True)
        for name in found:
            try:
                (self.dir / name).replace(backup / name)
            except OSError:
                logging.warning("Ancien fichier non range : %s", name, exc_info=True)
        logging.info("Donnees importees depuis %d ancien(s) fichier(s) JSON "
                     "(ranges dans %s)", len(found), backup)

    # ------------------------------------------------------------ io interne
    @staticmethod
    def _load(path: Path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            pass   # premier lancement, ou fichier pas encore cree : normal
        except Exception:
            logging.warning("Lecture impossible de %s, valeurs par defaut utilisees",
                            path, exc_info=True)
        return default

    def _write_all(self, names, meta=None, extra=None):
        """Ecriture immediate (hors debounce) des depots nommes, et des
        informations `meta` sur la base, dans une seule transaction (a
        laquelle `extra`, appelee avec le curseur, peut joindre ses ecritures)."""
        changes = [(self._repos[n], *self._repos[n].pending_changes()) for n in names]
        with self.db.transaction() as cur:
            for repo, upserts, deletes in changes:
                repo.write(cur, upserts, deletes)
            if extra is not None:
                extra(cur)
            for key, value in (meta or {}).items():
                Database.set_meta(cur, key, value)
        for repo, upserts, deletes in changes:
            repo.mark_written(upserts, deletes)

    def _schedule(self, name: str, *keys):
        """Marque un depot comme a sauvegarder et repousse l'echeance : tant
        que des modifications arrivent, l'ecriture est differee de SAVE_DELAY.
        `keys` : seules cles modifiees du depot, les seules a serialiser (un
        tour de page ne serialise plus toute la progression) ; sans cle, tout
        le depot sera compare a ce qui est en base."""
        with self._save_lock:
            self._dirty.add(name)
            if not keys:
                self._dirty_keys[name] = None
            else:
                pending = self._dirty_keys.get(name, set())
                if pending is not None:
                    pending.update(keys)
                    self._dirty_keys[name] = pending
            self._deadline = time.monotonic() + SAVE_DELAY
            if self._saver is None:
                self._saver = threading.Thread(
                    target=self._saver_loop, name="beheread-store-saver", daemon=True)
                self._saver.start()
        self._wake.set()

    def _saver_loop(self):
        """Thread de sauvegarde unique : attend une demande, laisse passer
        SAVE_DELAY sans nouvelle modification (debounce), puis ecrit."""
        while True:
            self._wake.wait()
            with self._save_lock:
                deadline = self._deadline
                if deadline is None:
                    self._wake.clear()   # rien en attente (deja ecrit par flush)
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._deadline = None
                    self._wake.clear()
            if remaining > 0:
                time.sleep(min(remaining, SAVE_DELAY))
                continue
            self._flush()

    def _flush(self) -> bool:
        """Ecrit tout ce qui est en attente. Renvoie False si une partie n'a pas
        pu etre serialisee et reste donc en attente (nouvel essai programme)."""
        # _io_lock est pris AVANT de prelever les depots en attente : deux
        # flush concurrents (thread de sauvegarde, flush() du thread UI)
        # s'executent l'un apres l'autre - une serialisation ancienne ne peut
        # plus etre ecrite apres une plus recente - et close() attend la fin
        # d'un flush en cours au lieu d'en perdre les modifications.
        # Le calcul des lignes modifiees (serialisation JSON) se fait sous
        # _save_lock, puis la base est ecrite en dehors (l'io ne bloque pas les
        # setters, qui ne prennent que _save_lock). Les setters mutent les
        # dicts sans verrou (thread UI, ScanWorker) : un json.dumps concurrent
        # peut lever "dictionary changed size during iteration". Le depot est
        # alors remis en attente et retente, au lieu d'etre abandonne en silence.
        retry = False
        with self._io_lock:
            if self._closed:
                return True
            with self._save_lock:
                dirty, self._dirty = self._dirty, set()
                dirty_keys, self._dirty_keys = self._dirty_keys, {}
                changes = []
                for name in dirty:
                    only = dirty_keys.get(name)
                    for repo_name in DIRTY_TO_REPOS.get(name, (name,)):
                        repo = self._repos[repo_name]
                        try:
                            upserts, deletes = repo.pending_changes(only)
                        except RuntimeError:
                            logging.info("Modification concurrente de %s pendant la "
                                         "serialisation, nouvel essai", repo.table)
                            self._dirty.add(name)
                            self._dirty_keys[name] = None
                            retry = True
                            continue
                        except Exception:
                            logging.error("Serialisation impossible de %s, "
                                          "sauvegarde perdue pour ce cycle", repo.table,
                                          exc_info=True)
                            continue
                        if upserts or deletes:
                            changes.append((repo, upserts, deletes))
                if retry and self._deadline is None:
                    self._deadline = time.monotonic() + SAVE_DELAY
            if changes:
                try:
                    with self.db.transaction() as cur:
                        for repo, upserts, deletes in changes:
                            repo.write(cur, upserts, deletes)
                except Exception:
                    logging.error("Ecriture en base impossible, nouvel essai "
                                  "au prochain cycle", exc_info=True)
                    with self._save_lock:
                        for repo, _u, _d in changes:
                            self._dirty.add(REPO_TO_DIRTY[repo.table])
                            self._dirty_keys[REPO_TO_DIRTY[repo.table]] = None
                    return False
                for repo, upserts, deletes in changes:
                    repo.mark_written(upserts, deletes)
        if retry:
            self._wake.set()
        return not retry

    def flush(self):
        """Force l'ecriture immediate de tout ce qui est en attente. A appeler
        a la fermeture de l'application (aboutToQuit / closeEvent)."""
        with self._save_lock:
            self._deadline = None
        for _ in range(5):   # retente si un autre thread mutait pendant la serialisation
            if self._flush():
                return
        logging.error("Sauvegarde incomplete a la fermeture (modifications concurrentes)")

    def close(self):
        """Ecrit ce qui reste en attente puis ferme la base (fin de
        l'application). Les sauvegardes demandees ensuite sont ignorees."""
        if self._closed:
            return
        self.flush()
        with self._io_lock:
            self._closed = True
            self.db.maintenance()
            self.db.close()

    def _migrate_meta_cache_out_of_settings(self):
        """Les deux caches de metadonnees vivaient autrefois dans settings.json
        (qu'ils faisaient grossir). On les sort une fois pour toutes vers leurs
        propres depots pour garder les preferences legeres."""
        moved = False
        legacy_vol = self.settings.pop("volume_meta_cache", None)
        legacy_ser = self.settings.pop("series_meta_cache", None)
        if legacy_vol is not None:
            self.meta_cache.setdefault("volume", {}).update(legacy_vol)
            moved = True
        if legacy_ser is not None:
            self.meta_cache.setdefault("series", {}).update(legacy_ser)
            moved = True
        if moved:
            self._schedule("settings")
            self._schedule("meta")

    # ------------------------------------------------------------ identite par contenu
    def key_for(self, path: str, st=None) -> str:
        """Empreinte de contenu du fichier, mise en cache (validee par
        mtime+taille). Repli sur le chemin si le fichier est illisible.
        Memorise pour la session (voir _key_memo) : seul le premier appel apres
        un scan touche au disque. `st` : stat deja obtenu par le scan,
        sur lequel l'empreinte est revalidee sans appel systeme."""
        scanned = st is not None
        if not scanned:
            memo = self._key_memo.get(path)
            if memo is not None:
                return memo
            try:
                st = os.stat(path)
            except OSError:
                return path
        cached = self._fp.get(path)
        if cached and cached.get("m") == st.st_mtime_ns and cached.get("s") == st.st_size:
            self._key_memo[path] = cached["k"]
            return cached["k"]
        # fichier cloud non telecharge : lire son contenu declencherait un
        # telechargement complet et bloquant. Repli temporaire sur le chemin
        # (non memorise) ; l'empreinte reelle sera calculee une fois le fichier
        # en local, et les caches indexes par chemin migreront a ce moment-la
        # (meme mecanisme que les entrees heritees, cf. _progress_entry).
        if is_cloud_stat(st) if scanned else is_cloud_placeholder(path):
            return path
        try:
            key = _compute_fingerprint(path)
        except OSError:
            return path
        with self._save_lock:   # appele aussi depuis le ScanWorker
            self._fp[path] = {"m": st.st_mtime_ns, "s": st.st_size, "k": key}
        self._key_memo[path] = key
        self._schedule("fp", path)
        return key

    def invalidate_key_memo(self):
        """Oublie les empreintes memorisees pour la session : le prochain
        key_for de chaque chemin revalide son empreinte (mtime+taille). Appele
        au debut de chaque scan, qui voit ainsi les fichiers modifies sur place."""
        self._key_memo.clear()

    def note_renamed(self, old_path: str, new_path: str):
        """Suit un renommage de fichier : reindexe l'empreinte (le seul cache
        indexe par chemin) sur le nouveau chemin, pour eviter de relire le
        fichier et de laisser une entree morte. Progression, metadonnees,
        vignettes et regroupements manuels sont indexes par contenu et suivent
        donc automatiquement le fichier renomme."""
        old_path, new_path = str(Path(old_path)), str(Path(new_path))
        self._key_memo.pop(old_path, None)
        entry = self._fp.pop(old_path, None)
        if entry is not None:
            self._fp[new_path] = entry
            self._schedule("fp", new_path)

    # ------------------------------------------------------------ nettoyage des caches
    def purge_orphan_caches(self, current_paths):
        """Retire du disque les vignettes en cache et les empreintes indexees
        par chemin qui ne correspondent plus a aucun fichier de la
        bibliotheque. N'est appele qu'a la fin d'un vrai scan (pas au demarrage
        offline) : `current_paths` reflete alors l'ensemble reel des fichiers.

        Volontairement conservateur : on ne touche NI a la progression, NI aux
        metadonnees, NI aux regroupements manuels (indexes par contenu). Un
        fichier momentanement absent - disque reseau deconnecte, cle USB
        retiree - ne doit pas perdre sa progression de lecture. Seuls des caches
        regenerables (vignette) ou recalculables (empreinte par chemin) sont
        purges."""
        current_paths = {str(Path(p)) for p in current_paths}

        # empreintes indexees par chemin : retire celles dont le chemin a disparu
        stale = [p for p in list(self._fp) if p not in current_paths]
        if stale:
            for p in stale:
                self._fp.pop(p, None)
                self._key_memo.pop(p, None)
            self._schedule("fp", *stale)   # suppressions seules : rien a reserialiser

        # vignettes : garde uniquement les fichiers attendus pour les tomes
        # actuels (le nom encode l'empreinte de contenu + le facteur d'echelle)
        try:
            wanted = {self.thumb_path(p).name for p in current_paths}
        except Exception:
            logging.warning("Purge des vignettes ignoree (calcul des noms impossible)",
                            exc_info=True)
            return
        try:
            existing = list(self.thumb_dir.glob("*.jpg"))
        except OSError:
            return
        for f in existing:
            if f.name not in wanted:
                try:
                    f.unlink()
                except OSError:
                    logging.debug("Vignette orpheline non supprimee : %s", f, exc_info=True)

    def forget_content(self, key: str, path: str):
        """Oublie les donnees rattachees a un fichier qui vient d'etre supprime
        du disque : progression, date d'ajout et metadonnees du tome.

        `key` doit avoir ete resolu AVANT la suppression (key_for doit lire le
        fichier encore present). A n'appeler qu'une fois la suppression
        reussie : un echec (fichier verrouille, droits) ne doit rien effacer.
        Si une autre copie identique (meme empreinte) est encore connue, ses
        donnees - partagees par contenu - sont conservees."""
        path = str(Path(path))
        self._key_memo.pop(path, None)
        with self._save_lock:
            if self._fp.pop(path, None) is not None:
                self._schedule("fp")
            shared = any(v.get("k") == key for v in self._fp.values())
        if shared:
            return
        # couverture choisie : image copiee supprimee avec le tome
        choice = self.settings.get("covers", {}).pop(key, None)
        if isinstance(choice, dict) and choice.get("image"):
            (self.cover_dir / Path(choice["image"]).name).unlink(missing_ok=True)
            self._schedule("settings")
        # cle de contenu ET eventuelle entree heritee indexee par chemin
        for name, data in (("progress", self.progress), ("added", self._added),
                           ("meta", self.meta_cache.get("volume", {}))):
            removed = [data.pop(key, None), data.pop(path, None)]
            if any(r is not None for r in removed):
                self._schedule(name)

    # ------------------------------------------------------------ dossiers sources
    def folders(self):
        return list(self.settings.get("folders", []))

    def add_folder(self, folder: str) -> bool:
        folder = str(Path(folder))
        if folder in self.settings["folders"]:
            return False
        self.settings["folders"].append(folder)
        self._schedule("settings")
        self.flush()   # operation rare et importante : ecriture immediate
        return True

    def set_folders(self, folders):
        """Remplace la liste complete des dossiers sources (normalises,
        sans doublon, ordre preserve). Utilise par le panneau de gestion."""
        seen = set()
        cleaned = []
        for f in folders:
            f = str(Path(f))
            if f not in seen:
                seen.add(f)
                cleaned.append(f)
        self.settings["folders"] = cleaned
        self._schedule("settings")
        self.flush()

    # ------------------------------------------------- regroupement manuel en serie
    # Un tome peut etre rattache manuellement a une serie (glisser-deposer) ou
    # au contraire detache de son regroupement automatique (clic droit). Comme
    # la progression, ces choix sont indexes par empreinte de contenu : ils
    # survivent a un renommage ou a un deplacement du fichier.
    def series_override(self, path: str):
        """Renvoie le nom de serie force pour ce tome, la sentinelle de
        detachement (Store.SERIES_DETACHED), ou None si regroupement
        automatique."""
        return self._overrides.get(self.key_for(path))

    def set_series_override(self, path: str, value: str):
        key = self.key_for(path)
        self._overrides[key] = value
        self._schedule("overrides", key)
        self.flush()

    def clear_series_override(self, path: str):
        key = self.key_for(path)
        if self._overrides.pop(key, None) is not None:
            self._schedule("overrides", key)
            self.flush()

    # ------------------------------------------------- nom affiche d'une serie
    # Renommage manuel d'un dossier de serie (affichage uniquement) : indexe
    # par cle de serie normalisee, il ne change ni les fichiers ni le
    # regroupement.
    def series_name(self, series_key: str):
        return self.settings.get("series_names", {}).get(series_key)

    def set_series_name(self, series_key: str, name):
        names = self.settings.setdefault("series_names", {})
        if name:
            names[series_key] = name
        else:
            names.pop(series_key, None)
        self._schedule("settings")

    # ------------------------------------------- tomes parus dans l'edition possedee
    # Saisi a la main (« Modifier les informations… » de la serie) quand
    # l'edition possedee ne suit pas le decoupage trouve en ligne (edition
    # Perfect, double...). Prioritaire sur le nombre trouve en ligne.
    def series_published(self, series_key: str):
        value = self.settings.get("series_published", {}).get(series_key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 \
            else None

    def set_series_published(self, series_key: str, count):
        published = self.settings.setdefault("series_published", {})
        if isinstance(count, int) and count > 0:
            published[series_key] = count
        else:
            published.pop(series_key, None)
        self._schedule("settings")

    # ------------------------------------------- nature de publication d'une serie
    # « Publiée en » tomes ou chapitres (voir core/units.py), indexee par cle
    # de serie normalisee ; absente = detection automatique.
    def series_nature(self, series_key: str) -> str:
        value = self.settings.get("series_nature", {}).get(series_key)
        return value if value in (units.VOLUMES, units.CHAPTERS) else units.AUTO

    def set_series_nature(self, series_key: str, nature: str):
        natures = self.settings.setdefault("series_nature", {})
        if nature in (units.VOLUMES, units.CHAPTERS):
            natures[series_key] = nature
        else:
            natures.pop(series_key, None)
        self._schedule("settings")

    # --------------------------------------- decoupage officiel tomes/chapitres
    # Cache de MangaDex (voir mangadex.chapter_ranges), indexe par cle de
    # serie : {"at": horodatage, "id": oeuvre MangaDex ou None, "ranges":
    # {tome: [premier, dernier chapitre]}}. Redemande periodiquement : un
    # tome qui parait range de nouveaux chapitres.
    def chapter_map(self, series_key: str):
        value = self.settings.get("chapter_maps", {}).get(series_key)
        return value if isinstance(value, dict) else None

    def set_chapter_map(self, series_key: str, data: dict):
        self.settings.setdefault("chapter_maps", {})[series_key] = data
        self._schedule("settings")

    # ------------------------------------------------------------ tomes virtuels
    # Chapitres regroupes en un tome (voir infra/virtual.py), par identifiant :
    # {"series": cle de serie, "name": nom de serie, "number": numero,
    # "chapters": [empreintes de contenu des chapitres, dans l'ordre]}. Les
    # empreintes, comme pour la progression, survivent a un renommage ou a un
    # deplacement des fichiers.
    def virtual_volumes(self) -> dict:
        value = self.settings.get("virtual_volumes")
        return {k: v for k, v in value.items() if isinstance(v, dict)} \
            if isinstance(value, dict) else {}

    def set_virtual_volume(self, volume_id: str, data: dict):
        self.settings.setdefault("virtual_volumes", {})[volume_id] = data
        self._schedule("settings")

    def remove_virtual_volume(self, volume_id: str):
        if self.settings.get("virtual_volumes", {}).pop(volume_id, None) is not None:
            self._schedule("settings")

    def manual_chapter_ranges(self, series_key: str) -> dict:
        """Chapitres des tomes officiels arrives a la place d'un tome virtuel
        ({numero de tome (texte): [premier, dernier chapitre]}), qui
        completent le decoupage de MangaDex (voir chapter_ranges)."""
        value = self.settings.get("chapter_ranges_manual", {}).get(series_key)
        return value if isinstance(value, dict) else {}

    def set_manual_chapter_range(self, series_key: str, number: str, span):
        ranges = self.settings.setdefault("chapter_ranges_manual", {})
        ranges.setdefault(series_key, {})[number] = list(span)
        self._schedule("settings")

    def chapter_ranges(self, series_key: str) -> dict:
        """Decoupage tomes/chapitres connu : MangaDex, complete et corrige par
        les tomes arrives a la place d'un tome virtuel."""
        cached = self.chapter_map(series_key) or {}
        # decoupage d'une version anterieure (voir mangadex.RANGES_VERSION) :
        # ignore en attendant d'etre redemande
        ranges = dict(cached.get("ranges") or {}) if cached.get("v") == mangadex.RANGES_VERSION else {}
        ranges.update(self.manual_chapter_ranges(series_key))
        return ranges

    def latest_releases(self, series_key: str):
        """(dernier tome, dernier chapitre) parus d'apres MangaDex (parution
        japonaise pour les tomes), None pour chacun s'il est inconnu."""
        cached = self.chapter_map(series_key) or {}
        if cached.get("v") != mangadex.RANGES_VERSION:
            return None, None
        volume, chapter = cached.get("last_volume"), cached.get("last_chapter")
        return (volume if isinstance(volume, int) else None,
                chapter if isinstance(chapter, (int, float)) and not isinstance(chapter, bool)
                else None)

    def virtual_dismissed(self, series_key: str) -> set:
        """Numeros des tomes virtuels que l'utilisateur a dissocies : ils ne
        sont plus recrees automatiquement (voir VirtualMixin)."""
        value = self.settings.get("virtual_dismissed", {}).get(series_key)
        if isinstance(value, int) and not isinstance(value, bool):
            return {value}   # ancienne forme : un seul numero
        return {n for n in value if isinstance(n, int)} if isinstance(value, list) else set()

    def dismiss_virtual(self, series_key: str, number):
        numbers = self.virtual_dismissed(series_key) | {int(number)}
        self.settings.setdefault("virtual_dismissed", {})[series_key] = sorted(numbers)
        self._schedule("settings")

    # ------------------------------------------------ « Continuer la lecture »
    def continue_dismissed(self) -> dict:
        """{empreinte: horodatage} des tomes masques de la bande « Continuer
        la lecture » (ils y reviennent s'ils sont relus apres ce masquage)."""
        return self._dismissed

    def dismiss_continue(self, path: str):
        key = self.key_for(path)
        self._dismissed[key] = time.time()
        self._schedule("dismissed", key)

    # ------------------------------------------------------- sens de lecture
    # Choix explicite de l'utilisateur (manga = droite->gauche), memorise par
    # tome (empreinte de contenu) s'il est seul, ou par serie (cle normalisee,
    # cf. series.normalize_name) s'il appartient a une serie a plusieurs
    # tomes : changer le sens sur un tome d'une serie s'applique alors a tous
    # ses tomes, pas seulement a celui ouvert.
    def reading_direction(self, path: str, series_key):
        """Renvoie True/False (manga_mode) si un choix explicite existe pour
        ce tome/cette serie, sinon None (l'appelant doit alors se rabattre sur
        la detection automatique puis le reglage global par defaut)."""
        if series_key:
            v = self.settings.get("series_direction", {}).get(series_key)
            if v is not None:
                return bool(v)
        return self._directions.get(self.key_for(path))

    def set_reading_direction(self, path: str, series_key, manga_mode: bool):
        if series_key:
            self.settings.setdefault("series_direction", {})[series_key] = bool(manga_mode)
            self._schedule("settings")
        else:
            key = self.key_for(path)
            self._directions[key] = bool(manga_mode)
            self._schedule("directions", key)
        self.flush()

    # ------------------------------------------------------------ preferences
    def reader_pref(self, key, default=None):
        return self.settings.get("reader", {}).get(key, default)

    def set_reader_pref(self, key, value):
        self.settings.setdefault("reader", {})[key] = value
        self._schedule("settings")

    # Reglages du lecteur retenus par serie (double page, ajustement,
    # recadrage, decalage de parite) : un choix fait dans un tome vaut pour
    # toute sa serie, et devient aussi le reglage general que reprennent les
    # series sans choix propre. Indexes par cle de serie normalisee.
    def reader_setting(self, key, series_key, default=None):
        """Reglage du lecteur pour un tome : celui choisi dans sa serie, sinon
        le reglage general."""
        if series_key:
            value = self.settings.get("series_reader", {}).get(series_key, {}).get(key)
            if value is not None:
                return value
        return self.reader_pref(key, default)

    def set_reader_setting(self, key, value, series_key):
        self.set_reader_pref(key, value)
        if series_key:
            self.settings.setdefault("series_reader", {}).setdefault(series_key, {})[key] = value
            self._schedule("settings")

    def library_pref(self, key, default=None):
        return self.settings.get("library", {}).get(key, default)

    def set_library_pref(self, key, value):
        self.settings.setdefault("library", {})[key] = value
        self._schedule("settings")

    def ui_pref(self, key, default=None):
        return self.settings.get("ui", {}).get(key, default)

    def set_ui_pref(self, key, value):
        self.settings.setdefault("ui", {})[key] = value
        self._schedule("settings")

    # ------------------------------------------------------------ date d'ajout
    def ensure_added(self, paths):
        """Horodate chaque contenu encore inconnu et renvoie le dict
        chemin -> timestamp. Un seul chemin d'ecriture pour tout un scan."""
        added = self._added
        now = time.time()
        changed = []
        result = {}
        for p in paths:
            k = self.key_for(p)
            if k not in added:
                added[k] = now
                changed.append(k)
            result[p] = added[k]
        if changed:
            self._schedule("added", *changed)
        return result

    # ------------------------------------------------------------ progression
    def _progress_entry(self, path: str):
        """Entree de progression pour ce fichier (par empreinte de contenu),
        avec migration a la volee d'une eventuelle entree indexee par chemin."""
        key = self.key_for(path)
        entry = self.progress.get(key)
        if entry is not None:
            return entry, key
        legacy = self.progress.pop(path, None)
        if legacy is not None:
            self.progress[key] = legacy
            self._schedule("progress")
            return legacy, key
        return None, key

    def get_progress(self, path: str):
        """Retourne (page, total, termine) ou None."""
        entry, _ = self._progress_entry(path)
        if not entry:
            return None
        return entry.get("page", 0), entry.get("total", 0), entry.get("finished", False)

    def set_progress(self, path: str, page: int, total: int, finished: bool):
        entry, key = self._progress_entry(path)
        entry = entry or {}
        entry.update({"page": page, "total": total, "finished": finished,
                      "ts": time.time()})   # horodatage : sert a la rangee "Reprendre"
        self.progress[key] = entry
        self._schedule("progress", key)

    def progress_ts(self, path: str) -> float:
        """Date de derniere lecture (epoch) pour ce fichier, ou 0."""
        entry, _ = self._progress_entry(path)
        return float(entry.get("ts", 0)) if entry else 0.0

    def remove_progress(self, path: str):
        key = self.key_for(path)
        if self.progress.pop(key, self.progress.pop(path, None)) is not None:
            self._schedule("progress")

    # ------------------------------------------------------------ appareil (statistiques par PC)
    def device_id(self) -> str:
        """Identifiant stable de cet appareil (cree au premier appel)."""
        dev = self.settings.setdefault("device", {})
        if not dev.get("id"):
            dev["id"] = uuid.uuid4().hex
            dev["name"] = platform.node() or "PC"
            self._schedule("settings")
        return dev["id"]

    def device_name(self) -> str:
        self.device_id()
        return self.settings["device"].get("name") or "PC"

    # ------------------------------------------------------------ statistiques
    def record_reading(self, path: str, pages: int, seconds: float, finished: bool,
                       title: str, series: str, date=None):
        """Ajoute une seance de lecture (ou une fin de tome) au journal de cet
        appareil : une ligne, ecrite sur-le-champ. Un echec est consigne sans
        etre propage - les statistiques ne doivent jamais empecher de fermer
        un tome."""
        if pages <= 0 and seconds <= 0 and not finished:
            return
        device, name, key = self.device_id(), self.device_name(), self.key_for(path)
        try:
            with self._io_lock:
                if self._closed:
                    return
                self.reading_log.add(device, name, date or datetime.date.today(), key,
                                     pages, seconds, finished, title, series, time.time())
                self._pace_cache = None
                self._volume_paces_cache = None
        except Exception:
            logging.error("Seance de lecture non enregistree dans le journal", exc_info=True)

    def _import_finished_history(self):
        """Une seule fois (marqueur en base) : inscrit au journal les tomes
        termines avant son premier jour, dates de leur derniere lecture (voir
        stats.finished_before_journal). Sans cela, les fins de tome
        anterieures au journal disparaitraient des statistiques."""
        first = self.reading_log.first_day()
        before = first or datetime.date.today() + datetime.timedelta(days=1)
        rows = stats_model.finished_before_journal(self.progress, before)
        device, name = (self.device_id(), self.device_name()) if rows else (None, None)
        with self.db.transaction() as cur:
            for day, key in rows:
                self.reading_log.add(device, name, day, key, 0, 0, True, "", "",
                                     time.time(), cur)
            Database.set_meta(cur, FINISHED_HISTORY_KEY, f"{len(rows)} tome(s)")

    # ------------------------------------------------------------ sauvegarde (export / import)
    def backup_data(self) -> dict:
        """Contenu d'une sauvegarde de cet appareil (export, synchronisation)."""
        return backup_model.build_backup(self._backup_settings(), self.progress,
                                         self.reading_log.export(),
                                         self.meta_cache, self.continue_dismissed(),
                                         self.device_id(), self.device_name())

    def export_backup(self, path):
        backup_model.write_json_atomic(path, self.backup_data())

    @staticmethod
    def read_backup(path) -> dict:
        """Lit une sauvegarde sans rien fusionner (sans etat : utilisable hors
        du thread UI). Leve ValueError si le fichier n'en est pas une."""
        # un fichier quelconque choisi par l'utilisateur : rien n'est charge
        # en memoire au-dela de ce qu'une vraie sauvegarde peut peser
        if os.path.getsize(path) > MAX_BACKUP_BYTES:
            raise ValueError(tr("Ce fichier est trop volumineux pour être une sauvegarde Beheread."))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not backup_model.is_valid(data):
            raise ValueError(tr("Ce fichier n'est pas une sauvegarde Beheread."))
        return data

    def import_backup(self, path) -> dict:
        """Fusionne une sauvegarde (voir backup.py). Leve ValueError si le
        fichier n'en est pas une. Renvoie {"progress": n, "extras": m}."""
        return self.merge_backup(self.read_backup(path))

    def merge_backup(self, data) -> dict:
        """Fusionne le contenu d'une sauvegarde deja validee (read_backup)."""
        progress = len(backup_model.merge_progress(self.progress, data.get("progress", {})))
        if progress:
            self._schedule("progress")
        with self._io_lock:
            self.reading_log.replace_devices(backup_model.journal_sections_to_import(
                self.reading_log.devices(), data.get("stats", {}), self.device_id()))
        extras = backup_model.merge_extras(self._backup_settings(), self.meta_cache, data)
        if backup_model.merge_dismissed(self._dismissed, data.get("continue_dismissed", {})):
            self._schedule("dismissed")
        if extras:
            for name in ("settings", "meta", "overrides", "directions", "added", "pages"):
                self._schedule(name)
        self.flush()
        return {"progress": progress, "extras": extras}

    def export_reading_csv(self, path) -> int:
        """Ecrit le journal de lecture en CSV (separateur « ; », virgule
        decimale, UTF-8 avec BOM : ouvert tel quel par Excel en francais, et
        par LibreOffice ou Google Sheets). Renvoie le nombre de lignes."""
        rows = self.reading_log.csv_rows()
        tmp = Path(str(path) + ".tmp")
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            # separateurs du tableur de la langue : « ; » et virgule decimale en
            # francais, « , » et point en anglais
            out = csv.writer(f, delimiter=";" if language() == "fr" else ",")
            out.writerow([tr("Date"), tr("Appareil"), tr("Série"), tr("Tome"), tr("Pages lues"),
                          tr("Temps de lecture (min)"), tr("Séances"), tr("Tome terminé")])
            for day, device, series, title, pages, seconds, sessions, finished in rows:
                minutes = fmt_decimal((seconds or 0) / 60)
                out.writerow([day, device, series, title, pages, minutes, sessions,
                              "oui" if finished else ""])
        os.replace(tmp, path)
        return len(rows)

    def _backup_settings(self) -> dict:
        """Reglages par tome et par serie repris par une sauvegarde (voir
        backup.BACKUP_SETTINGS), sous leur nom d'echange : dictionnaires
        vivants, que merge_extras complete en place."""
        return {"series_overrides": self._overrides, "volume_direction": self._directions,
                "added": self._added, "pages": self._pages,
                "series_names": self.settings.setdefault("series_names", {}),
                "series_direction": self.settings.setdefault("series_direction", {}),
                "series_reader": self.settings.setdefault("series_reader", {}),
                "series_nature": self.settings.setdefault("series_nature", {}),
                "virtual_volumes": self.settings.setdefault("virtual_volumes", {}),
                "series_published": self.settings.setdefault("series_published", {}),
                "chapter_ranges_manual": self.settings.setdefault("chapter_ranges_manual", {})}

    # ------------------------------------------------------------ serveurs de lecture
    def servers(self) -> list:
        """Serveurs de lecture configures : [{"id", "kind", "name", "url",
        "user", "secret_enc"}] (voir infra/servers.py). Le mot de passe ou la
        cle d'API est protege comme le jeton AniList."""
        value = self.settings.get("servers")
        return [dict(s) for s in value if isinstance(s, dict)] if isinstance(value, list) else []

    def server_secret(self, server_id):
        for s in self.servers():
            if s.get("id") == server_id:
                return secret_store.unprotect(s.get("secret_enc"))
        return None

    def save_server(self, data: dict, secret=None):
        """Ajoute ou remplace un serveur (meme "id"). `secret` : nouveau mot
        de passe ou cle d'API, None pour garder celui enregistre."""
        servers = self.servers()
        old = next((s for s in servers if s.get("id") == data["id"]), None)
        entry = {k: data[k] for k in ("id", "kind", "name", "url", "user")}
        entry["secret_enc"] = (old or {}).get("secret_enc")
        if secret is not None:
            secret_store.discard(entry["secret_enc"])
            entry["secret_enc"] = secret_store.protect(secret, f"server-{data['id']}") if secret else None
        servers = [entry if s.get("id") == data["id"] else s for s in servers]
        if old is None:
            servers.append(entry)
        self.settings["servers"] = servers
        self._schedule("settings")
        self.flush()

    def remove_server(self, server_id):
        servers = self.servers()
        for s in servers:
            if s.get("id") == server_id:
                secret_store.discard(s.get("secret_enc"))
        self.settings["servers"] = [s for s in servers if s.get("id") != server_id]
        self._schedule("settings")
        self.flush()

    # ------------------------------------------------------------ AniList (suivi)
    def cloud_sync(self) -> dict:
        """Etat de la synchronisation par dossier cloud : folder, enabled,
        seen, signature, peers (voir services/cloud_sync.py)."""
        return self.settings.setdefault("cloud_sync", {})

    def touch_cloud_sync(self):
        self._schedule("settings")

    def anilist(self) -> dict:
        """Etat AniList de l'utilisateur : user, tracking, token_enc (voir
        anilist_tracker.py) ; les donnees par serie sont dans anilist_series.
        Le Client ID de l'application, lui, est dans beheread/config.py."""
        return self.settings.setdefault("anilist", {})

    def anilist_token(self):
        return secret_store.unprotect(self.anilist().get("token_enc"))

    def set_anilist_login(self, token, user_name):
        a = self.anilist()
        if token:
            a["token_enc"] = secret_store.protect(token)
            a["user"] = user_name
        else:
            secret_store.discard(a.pop("token_enc", None))
            a.pop("user", None)
        self._schedule("settings")
        self.flush()

    def set_anilist_value(self, name, value):
        if value is None:
            self.anilist().pop(name, None)
        else:
            self.anilist()[name] = value
        self._schedule("settings")

    def anilist_series(self, section: str) -> dict:
        """Dictionnaire par cle de serie : "map" (oeuvre associee),
        "pending" (mises a jour en attente), "last" (derniere mise a jour).
        Chacun a sa table (une ligne par serie)."""
        return self._repos[SPLIT_ANILIST[section]].data

    def touch_anilist(self):
        self._schedule("settings")
        for name in SPLIT_ANILIST.values():
            self._schedule(name)

    # ------------------------------------------------------------ estimation du temps de lecture
    PACE_DAYS = 180       # le rythme suit la lecture recente
    PACE_TTL = 60.0       # secondes : une requete SQL par minute au plus
    _pace_cache = None    # (instant, rythme)

    def reading_pace(self):
        """Rythme de lecture personnel (secondes par page) d'apres le journal
        de lecture des derniers mois (voir ReadingLog.pace), ou None tant que
        rien n'a ete lu. Memorise brievement : la bibliotheque le demande une
        fois par tome affiche, et une seance l'invalide (record_reading)."""
        now = time.monotonic()
        cached = self._pace_cache
        if cached is not None and now - cached[0] < self.PACE_TTL:
            return cached[1]
        since = datetime.date.today() - datetime.timedelta(days=self.PACE_DAYS)
        if self._closed:   # mises a jour en file tardives, apres la fermeture
            return None
        pace = self.reading_log.pace(since)
        self._pace_cache = (now, pace)
        return pace

    _volume_paces_cache = None    # (instant, {tome: (pages, secondes)})

    def volume_paces(self):
        """Pages lues et temps passe par tome, sur la meme periode et avec les
        memes lignes que reading_pace : de quoi calculer le rythme d'une
        serie (voir series_pace). Memorise comme reading_pace."""
        now = time.monotonic()
        cached = self._volume_paces_cache
        if cached is not None and now - cached[0] < self.PACE_TTL:
            return cached[1]
        if self._closed:
            return {}
        since = datetime.date.today() - datetime.timedelta(days=self.PACE_DAYS)
        rows = self.reading_log.volume_paces(since)
        self._volume_paces_cache = (now, rows)
        return rows

    def series_pace(self, volumes):
        """Rythme de lecture (secondes par page) propre a une serie, d'apres
        la lecture de ses tomes (empreintes `volumes`), ou None s'il y en a
        trop peu : une serie contemplative se lit plus vite qu'une serie
        bavarde, la moyenne generale (reading_pace) n'est que le repli."""
        return stats_model.pace_of(self.volume_paces(), volumes)

    def page_count(self, path: str):
        """Nombre de pages connu pour ce fichier (par empreinte de contenu),
        ou None. Renseigne lors de la generation de la vignette / de la lecture."""
        return self._pages.get(self.key_for(path))

    def set_page_count(self, path: str, n: int):
        if not n or n <= 0:
            return
        key = self.key_for(path)
        if self._pages.get(key) != n:
            self._pages[key] = int(n)
            self._schedule("pages", key)

    # ------------------------------------------------------------ cache metadonnees serie
    def series_meta(self, series_key: str):
        return self.meta_cache.get("series", {}).get(series_key)

    def set_series_meta(self, series_key: str, data):
        self.meta_cache.setdefault("series", {})[series_key] = data
        self._schedule("meta")

    def remove_series_meta(self, series_key: str):
        if self.meta_cache.get("series", {}).pop(series_key, None) is not None:
            self._schedule("meta")

    # ------------------------------------------------------------ cache metadonnees par tome
    def volume_meta(self, path: str):
        key = self.key_for(path)
        vol = self.meta_cache.setdefault("volume", {})
        data = vol.get(key)
        if data is None and path in vol:   # migration entree indexee par chemin
            data = vol.pop(path)
            vol[key] = data
            self._schedule("meta")
        return data

    def set_volume_meta(self, path: str, data):
        self.meta_cache.setdefault("volume", {})[self.key_for(path)] = data
        self._schedule("meta")

    def remove_volume_meta(self, path: str):
        vol = self.meta_cache.get("volume", {})
        key = self.key_for(path)
        if vol.pop(key, vol.pop(path, None)) is not None:
            self._schedule("meta")

    def clear_downloaded_meta(self) -> int:
        """Oublie les metadonnees obtenues en ligne (Google Books, AniList,
        MangaDex) et les resultats « introuvable », en conservant ce qui vient
        de ComicInfo.xml ou d'une saisie manuelle. Renvoie le nombre d'entrees
        retirees."""
        keep = ("comicinfo", "manual", "server")   # server : redonne a chaque liste
        removed = 0
        for section in ("volume", "series"):
            data = self.meta_cache.get(section, {})
            for k in [k for k, v in data.items()
                      if not (isinstance(v, dict) and v.get("source") in keep)]:
                del data[k]
                removed += 1
        if removed:
            self._schedule("meta")
        return removed

    # ------------------------------------------------------------ cache de vignettes
    def clear_thumbnails(self) -> int:
        """Supprime les vignettes en cache disque (elles sont regenerees a
        l'affichage). Renvoie le nombre de fichiers supprimes."""
        n = 0
        for f in self.thumb_dir.glob("*.jpg"):
            try:
                f.unlink()
                n += 1
            except OSError:
                logging.debug("Vignette non supprimee : %s", f, exc_info=True)
        return n

    # ------------------------------------------------------------ index de bibliotheque (offline-first)
    def load_library_index(self):
        """Dernier instantane connu de la bibliotheque (liste d'entrees), pour
        un affichage immediat au demarrage avant le rescan reel. [] si absent."""
        rows = [r for r in self._repos["entries"].data.values() if isinstance(r, dict)]
        rows.sort(key=lambda r: r.get("seq", 0) if isinstance(r.get("seq"), int) else 0)
        return [{k: v for k, v in r.items() if k != "seq"} for r in rows]

    def save_library_index(self, entries):
        """Persiste l'instantane de la bibliotheque (ecriture directe : appele
        une fois par scan, pas a chaque tour de page). Une ligne par tome :
        seules les lignes ajoutees, changees ou retirees sont ecrites."""
        data = self._repos["entries"].data
        data.clear()
        data.update(_index_rows(entries))
        try:
            with self._io_lock:
                self._write_all(["entries"])
        except Exception:
            logging.warning("Ecriture de l'instantane de bibliotheque impossible",
                            exc_info=True)

    # ------------------------------------------------------------ couverture choisie
    # Une page du tome, ou une image de l'ordinateur copiee dans le dossier
    # des donnees (le fichier du tome n'est jamais modifie). Indexee par
    # empreinte de contenu, comme la progression.
    def custom_cover(self, path: str):
        """{"page": n} ou {"image": chemin absolu}, ou None (premiere page)."""
        choice = self.settings.get("covers", {}).get(self.key_for(path))
        if not isinstance(choice, dict):
            return None
        if isinstance(choice.get("page"), int) and choice["page"] >= 0:
            return {"page": choice["page"]}
        image = choice.get("image")
        if isinstance(image, str) and (self.cover_dir / Path(image).name).is_file():
            return {"image": str(self.cover_dir / Path(image).name)}
        return None

    def set_custom_cover(self, path: str, page=None, image=None):
        """Retient la couverture choisie (une page, ou une QImage a copier) ;
        sans rien, revient a la premiere page. La vignette en cache est
        effacee : elle sera regeneree."""
        key = self.key_for(path)
        covers = self.settings.setdefault("covers", {})
        old = covers.pop(key, None)
        stored = self.cover_dir / (hashlib.sha1(key.encode("utf-8", "replace")).hexdigest() + ".jpg")
        if image is not None:
            self.cover_dir.mkdir(exist_ok=True)
            if not image.save(str(stored), "JPEG", 90):
                raise OSError(f"Image impossible a enregistrer : {stored}")
            covers[key] = {"image": stored.name}
        elif page:
            covers[key] = {"page": int(page)}
        if (image is None and isinstance(old, dict) and old.get("image")):
            _unlink_patiently(stored)   # image orpheline sinon : ecrasee au prochain choix
        _unlink_patiently(self.thumb_path(path))
        self._schedule("settings")

    def thumb_path(self, path: str) -> Path:
        """Chemin de la vignette en cache (JPEG : ~5x plus leger et plus rapide
        a encoder/relire qu'un PNG, difference invisible sur une vignette),
        indexe par empreinte de contenu : une couverture n'est pas regeneree
        si le fichier est deplace/renomme. Le facteur de resolution
        (THUMB_SCALE) fait partie du nom : l'augmenter regenere automatiquement
        des vignettes plus nettes au lieu de reutiliser indefiniment un cache
        genere a une resolution inferieure."""
        h = hashlib.sha1(self.key_for(path).encode("utf-8", "replace")).hexdigest()
        return self.thumb_dir / f"{h}_{THUMB_SCALE}x.jpg"
