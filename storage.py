"""Persistance locale : dossiers de la bibliotheque, progression de lecture,
cache des metadonnees et des vignettes. Tout est stocke dans
%APPDATA%/MangaReaderPy (ou ~/.manga-reader-py hors Windows). Aucune
connexion reseau.

Deux points d'architecture :

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

import hashlib
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

from lib_constants import THUMB_SCALE

SAVE_DELAY = 0.6          # secondes d'inactivite avant une ecriture differee
FP_HEAD = 65536           # octets de tete lus pour l'empreinte de contenu


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
        self.settings_file = self.dir / "settings.json"
        self.progress_file = self.dir / "progress.json"
        self.meta_file = self.dir / "meta_cache.json"
        self.fp_file = self.dir / "fingerprints.json"
        self.index_file = self.dir / "library_index.json"
        self.thumb_dir = self.dir / "thumbnails"
        self.thumb_dir.mkdir(exist_ok=True)

        self.settings = self._load(self.settings_file, {"folders": [], "reader": {}})
        self.progress = self._load(self.progress_file, {})
        self.meta_cache = self._load(
            self.meta_file, {"volume": {}, "series": {}})
        self._fp = self._load(self.fp_file, {})   # chemin -> {m, s, k}

        # ecritures differees
        self._save_lock = threading.RLock()
        self._dirty = set()
        self._timer = None

        self._migrate_meta_cache_out_of_settings()

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

    @staticmethod
    def _write_text(path: Path, text: str):
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        tmp.replace(path)

    def _targets(self):
        return {
            "settings": (self.settings_file, self.settings),
            "progress": (self.progress_file, self.progress),
            "meta": (self.meta_file, self.meta_cache),
            "fp": (self.fp_file, self._fp),
        }

    def _schedule(self, name: str):
        """Marque un fichier comme a sauvegarder et (re)arme le minuteur : tant
        que des modifications arrivent, l'ecriture est repoussee de SAVE_DELAY."""
        with self._save_lock:
            self._dirty.add(name)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(SAVE_DELAY, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self):
        # La serialisation JSON se fait SOUS le verrou : le thread UI mute
        # librement self.progress / self.settings entre deux tours de page, et
        # un json.dump concurrent leverait "dictionary changed size during
        # iteration" (silencieusement avale -> sauvegarde perdue). On fige donc
        # un instantane textuel sous verrou, puis on ecrit le disque en dehors
        # (l'io lente ne bloque pas les setters).
        with self._save_lock:
            dirty, self._dirty = self._dirty, set()
            self._timer = None
            targets = self._targets()
            snapshots = []
            for name in dirty:
                path, data = targets[name]
                try:
                    text = json.dumps(data, ensure_ascii=False, indent=2)
                except Exception:
                    logging.error("Serialisation impossible de %s, "
                                 "sauvegarde perdue pour ce cycle", path, exc_info=True)
                    continue
                snapshots.append((path, text))
        for path, text in snapshots:
            try:
                self._write_text(path, text)
            except Exception:
                logging.error("Ecriture disque impossible de %s, "
                             "sauvegarde perdue pour ce cycle", path, exc_info=True)

    def flush(self):
        """Force l'ecriture immediate de tout ce qui est en attente. A appeler
        a la fermeture de l'application (aboutToQuit / closeEvent)."""
        with self._save_lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._flush()

    def _migrate_meta_cache_out_of_settings(self):
        """Les deux caches de metadonnees vivaient autrefois dans settings.json
        (qu'ils faisaient grossir). On les sort une fois pour toutes dans
        meta_cache.json pour garder les preferences legeres."""
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
        mtime+taille). Repli sur le chemin si le fichier est illisible."""
        try:
            st = os.stat(path)
        except OSError:
            return path
        cached = self._fp.get(path)
        if cached and cached.get("m") == st.st_mtime_ns and cached.get("s") == st.st_size:
            return cached["k"]
        try:
            key = _compute_fingerprint(path)
        except OSError:
            return path
        self._fp[path] = {"m": st.st_mtime_ns, "s": st.st_size, "k": key}
        self._schedule("fp")
        return key

    def note_renamed(self, old_path: str, new_path: str):
        """Suit un renommage de fichier : reindexe l'empreinte (le seul cache
        indexe par chemin) sur le nouveau chemin, pour eviter de relire le
        fichier et de laisser une entree morte. Progression, metadonnees,
        vignettes et regroupements manuels sont indexes par contenu et suivent
        donc automatiquement le fichier renomme."""
        old_path, new_path = str(Path(old_path)), str(Path(new_path))
        entry = self._fp.pop(old_path, None)
        if entry is not None:
            self._fp[new_path] = entry
            self._schedule("fp")

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

    def remove_added(self, path: str):
        added = self.settings.get("added", {})
        k = self.key_for(path)
        if added.pop(k, added.pop(path, None)) is not None:
            self._schedule("settings")

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

    # ------------------------------------------------------------ estimation du temps de lecture
    def median_page_seconds(self):
        """Rythme de lecture personnel (secondes par page), lisse entre les
        sessions, ou None si jamais mesure."""
        v = self.settings.get("reader", {}).get("median_page_seconds")
        return float(v) if v else None

    def update_page_seconds(self, sample: float):
        """Integre le rythme median d'une session au rythme global par moyenne
        mobile exponentielle (les sessions recentes pesent davantage, sans
        qu'une session atypique ne fasse tout basculer)."""
        if not sample or sample <= 0:
            return
        old = self.median_page_seconds()
        blended = sample if old is None else (0.7 * old + 0.3 * sample)
        self.settings.setdefault("reader", {})["median_page_seconds"] = round(blended, 3)
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

    def get_reader_offset(self, path: str) -> int:
        """Decalage de parite double page (0 ou 1) memorise pour ce tome."""
        entry, _ = self._progress_entry(path)
        return int(entry.get("offset", 0)) if entry else 0

    def set_reader_offset(self, path: str, offset: int):
        entry, key = self._progress_entry(path)
        entry = entry or {}
        entry["offset"] = int(offset) & 1
        self.progress[key] = entry
        self._schedule("progress")

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

    # ------------------------------------------------------------ cache de vignettes
    # ------------------------------------------------------------ index de bibliotheque (offline-first)
    def load_library_index(self):
        """Dernier instantane connu de la bibliotheque (liste d'entrees), pour
        un affichage immediat au demarrage avant le rescan reel. [] si absent."""
        data = self._load(self.index_file, [])
        return data if isinstance(data, list) else []

    def save_library_index(self, entries):
        """Persiste l'instantane de la bibliotheque (ecriture directe : appele
        une fois par scan, pas a chaque tour de page)."""
        try:
            self._write_text(self.index_file,
                             json.dumps(entries, ensure_ascii=False, indent=2))
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
