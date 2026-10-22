"""Taches d'arriere-plan de la bibliotheque (QRunnable) : generation des
vignettes, recuperation des metadonnees (par tome et par serie), scan des
dossiers et comptage. Regroupees hors du widget principal, dont elles sont
independantes (elles ne communiquent que par signaux)."""

import logging
import os
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, Signal
from PySide6.QtGui import QImage

from beheread.config import THUMB_SCALE
from beheread.core.library_model import natural_key as _natural_key
from beheread.i18n import tr
from beheread.infra import metadata, relocate
from beheread.infra.archive import Archive, scan_tree
from beheread.infra.storage import Store, is_cloud_stat
from beheread.ui.library.constants import THUMB_H, THUMB_W


class _ThumbSignals(QObject):
    done = Signal(str, QImage)   # chemin du manga, image de couverture
    failed = Signal(str, str)    # chemin, message
    count = Signal(str, int)     # chemin, nombre de pages (estimations de temps)


def crop_to_size(img: QImage, target: QSize) -> QImage:
    """Met l'image a l'echelle pour COUVRIR `target` puis la rogne au centre :
    resultat exactement de la taille `target`, sans deformation."""
    scaled = img.scaled(target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (scaled.width() - target.width()) // 2)
    y = max(0, (scaled.height() - target.height()) // 2)
    return scaled.copy(x, y, min(target.width(), scaled.width()),
                       min(target.height(), scaled.height()))


class ThumbWorker(QRunnable):
    """Extrait la premiere image de l'archive et la reduit, hors du thread UI.

    Le cache disque reste a la resolution maximale (THUMB_SCALE) ; l'image
    emise est, elle, recadree a `display_size` - la plus grande taille
    reellement affichable sur les ecrans presents - pour ne pas garder en
    memoire des couvertures 3x trop grandes sur un ecran a 100%."""

    def __init__(self, manga_path: str, cache_path: Path, display_size: QSize, cover=None):
        super().__init__()
        self.manga_path = manga_path
        self.cache_path = cache_path
        self.display_size = display_size
        self.cover = cover or {}   # couverture choisie (Store.custom_cover)
        self.signals = _ThumbSignals()

    def run(self):
        try:
            if self.cache_path.exists():
                img = QImage(str(self.cache_path))
                if not img.isNull():
                    self.signals.done.emit(
                        self.manga_path, crop_to_size(img, self.display_size))
                    return
            ar = Archive(self.manga_path)
            try:
                page = self.cover.get("page", 0)
                if self.cover.get("image"):
                    img = QImage(self.cover["image"])
                else:
                    img = ar.read_image(page if page < len(ar) else 0,
                                        max_height=THUMB_H * THUMB_SCALE)
                self.signals.count.emit(self.manga_path, len(ar))
            finally:
                ar.close()
            if img.isNull():
                raise ValueError(tr("couverture illisible"))
            img = img.scaled(THUMB_W * THUMB_SCALE, THUMB_H * THUMB_SCALE,
                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
            # JPEG q=88 : ~5x plus petit qu'un PNG, encodage/relecture plus
            # rapides, sans difference visible a la taille d'une vignette.
            img.save(str(self.cache_path), "JPEG", 88)
            self.signals.done.emit(self.manga_path, crop_to_size(img, self.display_size))
        except Exception as e:
            logging.warning("Vignette impossible pour %s", self.manga_path, exc_info=True)
            self.signals.failed.emit(self.manga_path, str(e))


# ---------------------------------------------------------------- metadonnees (auteur, date)

class _MetaSignals(QObject):
    # chemin, donnees du tome (dict/None), donnees serie fraiches (dict/None), succes
    done = Signal(str, object, object, bool)


class MetaWorker(QRunnable):
    """Cascade de metadonnees d'un fichier, hors du thread UI (voir
    metadata.py pour le detail de la strategie)."""

    def __init__(self, path: str, series_name: str, volume, cached_series, online=True,
                 author_hint=None):
        super().__init__()
        self.author_hint = author_hint
        self.online = online   # False : ComicInfo.xml seul (pas de consentement)
        self.path = path
        self.series_name = series_name
        self.volume = volume
        self.cached_series = cached_series
        self.started = False   # voir MetadataController.prioritize
        self.signals = _MetaSignals()

    def run(self):
        self.started = True
        data, ok, series_data = None, False, None
        try:
            data, ok, series_data = metadata.fetch(
                self.path, self.series_name, self.volume, self.cached_series,
                online=self.online, author_hint=self.author_hint)
        except Exception:
            logging.exception("Metadonnees impossibles pour %s", self.path)
        finally:   # sans ce signal, le tome resterait « en cours » toute la session
            self.signals.done.emit(self.path, data, series_data, ok)


class _SeriesMetaSignals(QObject):
    done = Signal(str, object, bool)   # cle de serie, series_data (dict/None), succes


class SeriesMetaWorker(QRunnable):
    """Recherche au niveau de la serie (BnF, bases manga, Wikidata : une
    recherche pour tous ses tomes), pour faire apparaitre l'auteur
    rapidement au premier scan sans attendre les recherches par tome."""

    def __init__(self, series_key: str, series_name: str, author_hint=None):
        super().__init__()
        self.author_hint = author_hint
        self.series_key = series_key
        self.series_name = series_name
        self.signals = _SeriesMetaSignals()

    def run(self):
        series_data, ok = None, False
        try:
            series_data, ok = metadata.fetch_series(self.series_name, self.author_hint)
        except Exception:
            logging.exception("Metadonnees de serie impossibles pour %s", self.series_key)
        finally:
            self.signals.done.emit(self.series_key, series_data, ok)


def is_cloud_entry(path, st) -> bool:
    """Fichier cloud non telecharge, d'apres le stat du scan (sans le lire)."""
    return is_cloud_stat(st)


class ScanState:
    """Resultat d'un scan, garde pour le scan incremental suivant : fichiers
    trouves ({chemin: stat}) et dossiers parcourus."""

    def __init__(self, files, dirs):
        self.files = files
        self.dirs = dirs


def _norm(path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _within(path, folder) -> bool:
    """`path` est `folder` ou se trouve dessous (comparaison sans casse sous
    Windows, comme le systeme de fichiers)."""
    path, folder = _norm(path), _norm(folder)
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def dedupe_by_content(store: Store, paths, stats=None):
    """Deux fichiers identiques (meme contenu - copie du meme tome dans
    un autre dossier source, ou doublon au meme endroit) ne doivent
    apparaitre qu'une seule fois dans la bibliotheque. La progression,
    les metadonnees et la vignette sont deja partagees par empreinte de
    contenu (voir Store.key_for) : il suffit ici de ne garder qu'un seul
    chemin representant par empreinte, choisi de facon stable (ordre
    alphabetique) pour que ce ne soit jamais le meme fichier qui
    "disparaisse" arbitrairement d'un rafraichissement a l'autre.
    Le calcul des empreintes remplit au passage le cache de la Store."""
    kept = {}
    result = []
    stats = stats or {}
    for p in sorted(paths):
        try:
            key = store.key_for(p, stats.get(p))
        except Exception:
            key = p
        if key not in kept:
            kept[key] = p
            result.append(p)
    return result


class _ScanSignals(QObject):
    # chemins locaux (dedupliques par contenu), chemins cloud non telecharges,
    # tous les chemins locaux (copies identiques comprises, pour la purge des
    # caches), etat du scan (ScanState : surveillance, scan incremental)
    done = Signal(list, list, list, object)


class ScanWorker(QRunnable):
    """Scan des dossiers sources + deduplication par empreinte de contenu,
    hors du thread UI : sur un disque reseau ou une grosse bibliotheque, ce
    travail prend plusieurs secondes et figerait l'interface. Le calcul des
    empreintes remplit au passage le cache de la Store, si bien que la
    finalisation cote UI (parse des noms, overrides) reste instantanee.

    Scan complet, ou incremental : avec `previous` (ScanState du scan
    precedent) et `changed` (dossiers signales par la surveillance), seuls
    ces dossiers (et leurs sous-dossiers) sont reparcourus ; le reste est
    repris du scan precedent.

    Les fichiers cloud non telecharges (iCloud Drive/OneDrive) sont ecartes du
    resultat SANS etre lus (lire un seul octet forcerait leur telechargement
    complet) et renvoyes a part : la bibliotheque les met en file de
    telechargement en arriere-plan, et ils apparaitront au rescan suivant une
    fois leur contenu en local."""

    def __init__(self, store: Store, folders, previous=None, changed=None):
        super().__init__()
        self.store = store
        self.folders = list(folders)
        self.previous = previous
        self.changed = set(changed or ())
        self.signals = _ScanSignals()

    def _collect(self):
        """({chemin: stat}, [dossiers]) des dossiers sources."""
        if self.previous is not None and self.changed:
            files, dirs = dict(self.previous.files), set(self.previous.dirs)
            changed = [d for d in self.changed
                       if any(_within(d, f) for f in self.folders)]
            # les plus hauts d'abord : un sous-dossier d'un dossier deja
            # reparcouru n'est pas reparcouru une seconde fois
            outermost = [d for d in changed
                         if not any(o != d and _within(d, o) for o in changed)]
            for d in outermost:
                files = {p: st for p, st in files.items() if not _within(p, d)}
                dirs = {x for x in dirs if not _within(x, d)}
                found, subdirs = scan_tree(d)
                files.update(found)
                dirs.update(subdirs)
            return files, sorted(dirs)
        files, dirs = {}, []
        for folder in self.folders:
            try:
                found, subdirs = scan_tree(folder)
            except Exception:
                logging.warning("Scan impossible du dossier %s", folder, exc_info=True)
                continue
            files.update(found)
            dirs.extend(subdirs)
        return files, dirs

    def _ordered(self, files):
        """Chemins dans l'ordre des dossiers sources, en tri naturel dans
        chacun, sans doublon (dossiers imbriques)."""
        seen, ordered = set(), []
        for folder in self.folders:
            inside = sorted((p for p in files if _within(p, folder) and p not in seen),
                            key=_natural_key)
            seen.update(inside)
            ordered.extend(inside)
        return ordered

    def run(self):
        # revalide les empreintes (mtime+taille) : un fichier modifie sur place
        # depuis le dernier scan doit etre re-identifie
        self.store.invalidate_key_memo()
        files, dirs = self._collect()
        paths, cloud = [], []
        for p in self._ordered(files):
            (cloud if is_cloud_entry(p, files[p]) else paths).append(p)
        local = {p: files[p] for p in paths}
        self.signals.done.emit(dedupe_by_content(self.store, paths, local), cloud, paths,
                               ScanState(files, dirs))


class _HydrateSignals(QObject):
    done = Signal(str, bool)     # chemin, succes


class HydrateWorker(QRunnable):
    """Force le telechargement d'un fichier cloud (iCloud Drive/OneDrive) en
    le lisant en entier par blocs, hors du thread UI : le fournisseur cloud
    hydrate le fichier au fil de la lecture. Le contenu lu est jete - seul
    l'effet de bord (fichier desormais present en local) nous interesse."""

    CHUNK = 1024 * 1024

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.signals = _HydrateSignals()

    def run(self):
        ok = False
        try:
            with open(self.path, "rb") as f:
                while f.read(self.CHUNK):
                    pass
            ok = True
        except OSError:
            # hors ligne, quota iCloud, fichier disparu... : non bloquant, le
            # tome restera simplement absent de la bibliotheque cette session
            logging.warning("Telechargement cloud impossible pour %s",
                            self.path, exc_info=True)
        self.signals.done.emit(self.path, ok)


# ---------------------------------------------------------- deplacement de fichiers

class _MoveSignals(QObject):
    step = Signal(int, str)     # indice du fichier en cours, son nom
    done = Signal(object)       # bilan (voir MoveWorker.run)


class MoveWorker(QRunnable):
    """Deplace des fichiers d'un dossier source a un autre (voir
    infra/relocate.py), un a la fois, hors du thread UI. `cancel` : evenement
    qui arrete apres le fichier en cours."""

    def __init__(self, pairs, cancel):
        super().__init__()
        self.pairs = list(pairs)
        self.cancel = cancel
        self.signals = _MoveSignals()

    def run(self):
        result = {"moved": [], "exists": [], "busy": [], "errors": [], "left": []}
        for i, (src, dst) in enumerate(self.pairs):
            if self.cancel.is_set():
                result["left"] = self.pairs[i:]
                break
            self.signals.step.emit(i, Path(src).stem)
            try:
                status = relocate.move(src, dst)
            except OSError as e:
                logging.warning("Deplacement impossible : %s -> %s", src, dst, exc_info=True)
                result["errors"].append((src, str(e)))
                continue
            key = {relocate.MOVED: "moved", relocate.EXISTS: "exists",
                   relocate.BUSY: "busy"}[status]
            result[key].append((src, dst))
        self.signals.done.emit(result)


# ---------------------------------------------------------- appel ponctuel

class _PagesSignals(QObject):
    page = Signal(int, QImage)   # index, page reduite


class PagesWorker(QRunnable):
    """Pages reduites d'un tome, une a une (choix de la couverture), hors du
    thread UI ; `cancel()` arrete le parcours (fenetre fermee)."""

    def __init__(self, path: str, height: int):
        super().__init__()
        self.path = path
        self.height = height
        self.cancelled = False
        self.signals = _PagesSignals()

    def cancel(self):
        self.cancelled = True

    def run(self):
        try:
            ar = Archive(self.path)
        except Exception:
            logging.warning("Pages illisibles pour %s", self.path, exc_info=True)
            return
        try:
            for i in range(len(ar)):
                if self.cancelled:
                    return
                try:
                    img = ar.read_image(i, max_height=self.height)
                except Exception:
                    img = QImage()
                self.signals.page.emit(i, img)
        finally:
            ar.close()


class _CallSignals(QObject):
    done = Signal(object, object)   # resultat, exception (ou None)


class CallWorker(QRunnable):
    """Execute fn() hors du thread UI (requete reseau ponctuelle) ; le
    resultat, ou l'exception levee, revient par le signal `done`. L'appelant
    garde une reference a l'instance jusqu'a la reponse."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _CallSignals()

    def run(self):
        try:
            result = self.fn()
        except Exception as e:
            self.signals.done.emit(None, e)
            return
        self.signals.done.emit(result, None)


# ---------------------------------------------------------- gestion des dossiers

class _CountSignals(QObject):
    # dossier, nombre de mangas trouves, taille totale en octets (object :
    # un int de signal Qt est sur 32 bits, trop court au-dela de 2 Go)
    done = Signal(str, int, object)


class _FolderCountWorker(QRunnable):
    """Compte les fichiers CBZ/CBR d'un dossier et additionne leur taille hors
    du thread UI, pour afficher le nombre de mangas et la place qu'ils
    occupent sans figer le panneau a l'ouverture."""

    def __init__(self, folder: str):
        super().__init__()
        self.folder = folder
        self.signals = _CountSignals()

    def run(self):
        size = 0
        try:
            files, _dirs = scan_tree(self.folder)
            n = len(files)
            # taille logique : un fichier iCloud non telecharge compte aussi,
            # sans etre rapatrie pour autant
            size = sum(st.st_size for _path, st in files)
        except Exception:
            logging.warning("Comptage impossible du dossier %s", self.folder, exc_info=True)
            n = -1
        self.signals.done.emit(self.folder, n, size)
