"""Persistance locale : dossiers de la bibliotheque, progression de lecture,
cache des metadonnees et des vignettes. Tout est stocke dans
%APPDATA%/MangaReaderPy (ou ~/.manga-reader-py hors Windows). Aucune
connexion reseau.

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

import datetime
import hashlib
import json
import logging
import os
import platform
import sys
import threading
import time
import uuid
from pathlib import Path

from beheread.config import THUMB_SCALE
from beheread.core import backup as backup_model
from beheread.core import stats as stats_model
from beheread.infra import secret_store
from beheread.infra.database import Database, JsonTable
from beheread.infra.reading_log import ReadingLog

SAVE_DELAY = 0.6          # secondes d'inactivite avant une ecriture differee
DB_NAME = "beheread.db"

# depot -> table SQLite (voir database.py)
REPOS = {"settings": "settings", "progress": "progress", "volume_meta": "volume_meta",
         "series_meta": "series_meta", "fp": "fingerprints", "index": "library_index"}
# nom passe a _schedule -> depots a ecrire
DIRTY_TO_REPOS = {"settings": ("settings",), "progress": ("progress",),
                  "meta": ("volume_meta", "series_meta"), "fp": ("fp",)}
REPO_TO_DIRTY = {"settings": "settings", "progress": "progress", "volume_meta": "meta",
                 "series_meta": "meta", "fingerprints": "fp", "library_index": "settings"}
# anciens fichiers JSON (versions <= 0.1), importes au premier lancement
LEGACY_IMPORT_KEY = "legacy_json_import"
# fins de tome anterieures au journal de lecture, reprises une seule fois
FINISHED_HISTORY_KEY = "finished_history_import"
LEGACY_FILES = {"settings": "settings.json", "progress": "progress.json",
                "meta": "meta_cache.json", "fp": "fingerprints.json",
                "stats": "stats.json", "index": "library_index.json"}


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}
FP_HEAD = 65536           # octets de tete lus pour l'empreinte de contenu

# Attributs Windows des fichiers "cloud" (iCloud Drive, OneDrive) dont le
# contenu n'est PAS present sur le disque : le fichier n'est qu'un espace
# reserve, et la moindre lecture (meme 1 octet) declenche son telechargement
# complet et bloquant par le fournisseur cloud. On doit donc les detecter
# AVANT toute ouverture (os.stat suffit et ne declenche rien).
_FILE_ATTRIBUTE_OFFLINE = 0x00001000
_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
_CLOUD_PLACEHOLDER_ATTRS = (_FILE_ATTRIBUTE_OFFLINE
                            | _FILE_ATTRIBUTE_RECALL_ON_OPEN
                            | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)


def is_cloud_placeholder(path) -> bool:
    """True si le fichier est un espace reserve cloud non telecharge (iCloud
    Drive / OneDrive "libere de l'espace") : son contenu n'est pas en local et
    l'ouvrir forcerait un telechargement bloquant. Base uniquement sur les
    attributs retournes par os.stat, sans jamais ouvrir le fichier."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)   # absent hors Windows
    return bool(attrs & _CLOUD_PLACEHOLDER_ATTRS)


def data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", str(Path.home()))
        d = Path(base) / "MangaReaderPy"
    else:
        d = Path.home() / ".manga-reader-py"
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
        self._deadline = None              # echeance de la prochaine ecriture (monotonic)
        self._wake = threading.Event()
        self._saver = None
        self._closed = False

        if self.db.get_meta(LEGACY_IMPORT_KEY) is None:
            self._import_legacy_json()
        self.settings.setdefault("folders", [])
        self.settings.setdefault("reader", {})
        self._migrate_meta_cache_out_of_settings()
        # ancien rythme de lecture : il mesurait l'intervalle entre deux tours
        # de page, feuilletage compris, et non des secondes par page lue. Sans
        # rapport avec la mesure actuelle, il est oublie puis re-mesure.
        if self.settings["reader"].pop("median_page_seconds", None) is not None:
            self._schedule("settings")
        if self.db.get_meta(FINISHED_HISTORY_KEY) is None:
            self._import_finished_history()

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

    def _schedule(self, name: str):
        """Marque un fichier comme a sauvegarder et repousse l'echeance : tant
        que des modifications arrivent, l'ecriture est differee de SAVE_DELAY."""
        with self._save_lock:
            self._dirty.add(name)
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
        # Le calcul des lignes modifiees (serialisation JSON) se fait SOUS le
        # verrou, puis la base est ecrite en dehors (l'io ne bloque pas les
        # setters). Les setters, eux, mutent les dicts sans verrou (thread UI,
        # ScanWorker) : un json.dumps concurrent peut lever "dictionary changed
        # size during iteration". Le depot est alors remis en attente et
        # retente, au lieu d'etre abandonne en silence.
        retry = False
        with self._save_lock:
            dirty, self._dirty = self._dirty, set()
            changes = []
            for name in dirty:
                for repo_name in DIRTY_TO_REPOS[name]:
                    repo = self._repos[repo_name]
                    try:
                        upserts, deletes = repo.pending_changes()
                    except RuntimeError:
                        logging.info("Modification concurrente de %s pendant la "
                                     "serialisation, nouvel essai", repo.table)
                        self._dirty.add(name)
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
        if retry:
            self._wake.set()
        if changes:
            with self._io_lock:
                if self._closed:
                    return True
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
                    return False
                for repo, upserts, deletes in changes:
                    repo.mark_written(upserts, deletes)
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
    def key_for(self, path: str) -> str:
        """Empreinte de contenu du fichier, mise en cache (validee par
        mtime+taille). Repli sur le chemin si le fichier est illisible.
        Memorise pour la session (voir _key_memo) : seul le premier appel apres
        un scan touche au disque."""
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
        if is_cloud_placeholder(path):
            return path
        try:
            key = _compute_fingerprint(path)
        except OSError:
            return path
        with self._save_lock:   # appele aussi depuis le ScanWorker
            self._fp[path] = {"m": st.st_mtime_ns, "s": st.st_size, "k": key}
        self._key_memo[path] = key
        self._schedule("fp")
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
            self._schedule("fp")

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
            self._schedule("fp")

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
        # cle de contenu ET eventuelle entree heritee indexee par chemin
        for name, data in (("progress", self.progress),
                           ("settings", self.settings.get("added", {})),
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

    def remove_folder(self, folder: str):
        if folder in self.settings["folders"]:
            self.settings["folders"].remove(folder)
            self._schedule("settings")
            self.flush()

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
        return self.settings.get("series_overrides", {}).get(self.key_for(path))

    def set_series_override(self, path: str, value: str):
        self.settings.setdefault("series_overrides", {})[self.key_for(path)] = value
        self._schedule("settings")
        self.flush()

    def clear_series_override(self, path: str):
        ov = self.settings.get("series_overrides")
        if ov is not None:
            key = self.key_for(path)
            if key in ov:
                del ov[key]
                self._schedule("settings")
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

    # ------------------------------------------------ « Continuer la lecture »
    def continue_dismissed(self) -> dict:
        """{empreinte: horodatage} des tomes masques de la bande « Continuer
        la lecture » (ils y reviennent s'ils sont relus apres ce masquage)."""
        return self.settings.get("continue_dismissed", {})

    def dismiss_continue(self, path: str):
        self.settings.setdefault("continue_dismissed", {})[self.key_for(path)] = time.time()
        self._schedule("settings")

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
        return self.settings.get("volume_direction", {}).get(self.key_for(path))

    def set_reading_direction(self, path: str, series_key, manga_mode: bool):
        if series_key:
            self.settings.setdefault("series_direction", {})[series_key] = bool(manga_mode)
        else:
            self.settings.setdefault("volume_direction", {})[self.key_for(path)] = bool(manga_mode)
        self._schedule("settings")
        self.flush()

    # ------------------------------------------------------------ preferences
    def reader_pref(self, key, default=None):
        return self.settings.get("reader", {}).get(key, default)

    def set_reader_pref(self, key, value):
        self.settings.setdefault("reader", {})[key] = value
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
        added = self.settings.setdefault("added", {})
        now = time.time()
        changed = False
        result = {}
        for p in paths:
            k = self.key_for(p)
            if k not in added:
                added[k] = now
                changed = True
            result[p] = added[k]
        if changed:
            self._schedule("settings")
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
        self._schedule("progress")

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
    def export_backup(self, path):
        data = backup_model.build_backup(self.settings, self.progress, self.reading_log.export(),
                                         self.meta_cache, self.continue_dismissed(),
                                         self.device_id(), self.device_name())
        backup_model.write_json_atomic(path, data)

    def import_backup(self, path) -> dict:
        """Fusionne une sauvegarde (voir backup.py). Leve ValueError si le
        fichier n'en est pas une. Renvoie {"progress": n, "extras": m}."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not backup_model.is_valid(data):
            raise ValueError("Ce fichier n'est pas une sauvegarde Beheread.")
        progress = len(backup_model.merge_progress(self.progress, data.get("progress", {})))
        if progress:
            self._schedule("progress")
        with self._io_lock:
            self.reading_log.replace_devices(backup_model.journal_sections_to_import(
                self.reading_log.devices(), data.get("stats", {}), self.device_id()))
        dismissed = self.settings.setdefault("continue_dismissed", {})
        extras = backup_model.merge_extras(self.settings, self.meta_cache, data)
        if backup_model.merge_dismissed(dismissed, data.get("continue_dismissed", {})) or extras:
            self._schedule("settings")
            self._schedule("meta")
        self.flush()
        return {"progress": progress, "extras": extras}

    # ------------------------------------------------------------ AniList (suivi)
    def anilist(self) -> dict:
        """Etat AniList de l'utilisateur : user, tracking, token_enc, map,
        pending, last (voir anilist_tracker.py). Le Client ID de
        l'application, lui, est dans beheread/config.py."""
        return self.settings.setdefault("anilist", {})

    def anilist_token(self):
        return secret_store.unprotect(self.anilist().get("token_enc"))

    def set_anilist_login(self, token, user_name):
        a = self.anilist()
        if token:
            a["token_enc"] = secret_store.protect(token)
            a["user"] = user_name
        else:
            a.pop("token_enc", None)
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
        """Sous-dictionnaire par cle de serie : "map" (oeuvre associee),
        "pending" (mises a jour en attente), "last" (derniere mise a jour)."""
        return self.anilist().setdefault(section, {})

    def touch_anilist(self):
        self._schedule("settings")

    # ------------------------------------------------------------ estimation du temps de lecture
    def median_page_seconds(self):
        """Rythme de lecture personnel (secondes par page), lisse entre les
        sessions, ou None si jamais mesure."""
        v = self.settings.get("reader", {}).get("page_seconds")
        return float(v) if v else None

    def update_page_seconds(self, sample: float):
        """Integre le rythme median d'une session au rythme global par moyenne
        mobile exponentielle (les sessions recentes pesent davantage, sans
        qu'une session atypique ne fasse tout basculer)."""
        if not sample or sample <= 0:
            return
        old = self.median_page_seconds()
        blended = sample if old is None else (0.7 * old + 0.3 * sample)
        self.settings.setdefault("reader", {})["page_seconds"] = round(blended, 3)
        self._schedule("settings")

    def page_count(self, path: str):
        """Nombre de pages connu pour ce fichier (par empreinte de contenu),
        ou None. Renseigne lors de la generation de la vignette / de la lecture."""
        return self.settings.get("pages", {}).get(self.key_for(path))

    def set_page_count(self, path: str, n: int):
        if not n or n <= 0:
            return
        pages = self.settings.setdefault("pages", {})
        key = self.key_for(path)
        if pages.get(key) != n:
            pages[key] = int(n)
            self._schedule("settings")

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
        keep = ("comicinfo", "manual")
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
        data = self._repos["index"].data.get("entries", [])
        return data if isinstance(data, list) else []

    def save_library_index(self, entries):
        """Persiste l'instantane de la bibliotheque (ecriture directe : appele
        une fois par scan, pas a chaque tour de page)."""
        self._repos["index"].data["entries"] = list(entries)
        try:
            with self._io_lock:
                self._write_all(["index"])
        except Exception:
            logging.warning("Ecriture de l'instantane de bibliotheque impossible",
                            exc_info=True)

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
