"""Taches d'arriere-plan de la bibliotheque (QRunnable) : generation des
vignettes, recuperation des metadonnees (par tome et par serie), scan des
dossiers et comptage. Regroupees hors du widget principal, dont elles sont
independantes (elles ne communiquent que par signaux)."""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, Signal
from PySide6.QtGui import QImage

from beheread.config import THUMB_SCALE
from beheread.infra import metadata
from beheread.infra.archive import Archive, scan_folder
from beheread.infra.storage import Store, is_cloud_placeholder
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

    def __init__(self, manga_path: str, cache_path: Path, display_size: QSize):
        super().__init__()
        self.manga_path = manga_path
        self.cache_path = cache_path
        self.display_size = display_size
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
                img = ar.read_image(0, max_height=THUMB_H * THUMB_SCALE)
                self.signals.count.emit(self.manga_path, len(ar))
            finally:
                ar.close()
            if img.isNull():
                raise ValueError("couverture illisible")
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
    """Cascade ComicInfo.xml -> Google Books -> AniList pour un fichier,
    hors du thread UI (voir metadata.py pour le detail de la strategie)."""

    def __init__(self, path: str, series_name: str, volume, cached_series, online=True):
        super().__init__()
        self.online = online   # False : ComicInfo.xml seul (pas de consentement)
        self.path = path
        self.series_name = series_name
        self.volume = volume
        self.cached_series = cached_series
        self.signals = _MetaSignals()

    def run(self):
        data, ok, series_data = metadata.fetch(
            self.path, self.series_name, self.volume, self.cached_series,
            online=self.online)
        self.signals.done.emit(self.path, data, series_data, ok)


class _SeriesMetaSignals(QObject):
    done = Signal(str, object, bool)   # cle de serie, series_data (dict/None), succes


class SeriesMetaWorker(QRunnable):
    """Recherche AniList au niveau de la serie (une requete pour tous ses
    tomes), pour faire apparaitre l'auteur rapidement au premier scan sans
    attendre les recherches Google Books par tome (throttlees)."""

    def __init__(self, series_key: str, series_name: str):
        super().__init__()
        self.series_key = series_key
        self.series_name = series_name
        self.signals = _SeriesMetaSignals()

    def run(self):
        series_data, ok = metadata.fetch_series(self.series_name)
        self.signals.done.emit(self.series_key, series_data, ok)


def dedupe_by_content(store: Store, paths):
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
    for p in sorted(paths):
        try:
            key = store.key_for(p)
        except Exception:
            key = p
        if key not in kept:
            kept[key] = p
            result.append(p)
    return result


class _ScanSignals(QObject):
    # chemins locaux (dedupliques par contenu), chemins cloud non telecharges
    done = Signal(list, list)


class ScanWorker(QRunnable):
    """Scan recursif des dossiers sources + deduplication par empreinte de
    contenu, hors du thread UI : sur un disque reseau ou une grosse
    bibliotheque, ce travail (rglob + lecture de 64 Ko par fichier nouveau)
    prend plusieurs secondes et figerait l'interface s'il tournait sur l'UI.
    Le calcul des empreintes remplit au passage le cache de la Store, si bien
    que la finalisation cote UI (parse des noms, overrides) reste instantanee.

    Les fichiers cloud non telecharges (iCloud Drive/OneDrive) sont ecartes du
    resultat SANS etre lus (lire un seul octet forcerait leur telechargement
    complet) et renvoyes a part : la bibliotheque les met en file de
    telechargement en arriere-plan, et ils apparaitront au rescan suivant une
    fois leur contenu en local."""

    def __init__(self, store: Store, folders):
        super().__init__()
        self.store = store
        self.folders = list(folders)
        self.signals = _ScanSignals()

    def run(self):
        # revalide les empreintes (mtime+taille) : un fichier modifie sur place
        # depuis le dernier scan doit etre re-identifie
        self.store.invalidate_key_memo()
        seen = set()
        paths = []
        cloud = []
        for folder in self.folders:
            try:
                found = scan_folder(folder)
            except Exception:
                logging.warning("Scan impossible du dossier %s", folder, exc_info=True)
                found = []
            for p in found:
                if p in seen:
                    continue
                seen.add(p)
                if is_cloud_placeholder(p):
                    cloud.append(p)
                else:
                    paths.append(p)
        self.signals.done.emit(dedupe_by_content(self.store, paths), cloud)


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


# ---------------------------------------------------------- gestion des dossiers

class _CountSignals(QObject):
    done = Signal(str, int)      # dossier, nombre de mangas trouves


class _FolderCountWorker(QRunnable):
    """Compte les fichiers CBZ/CBR d'un dossier hors du thread UI, pour
    afficher le nombre de mangas sans figer le panneau a l'ouverture."""

    def __init__(self, folder: str):
        super().__init__()
        self.folder = folder
        self.signals = _CountSignals()

    def run(self):
        try:
            n = len(scan_folder(self.folder))
        except Exception:
            logging.warning("Comptage impossible du dossier %s", self.folder, exc_info=True)
            n = -1
        self.signals.done.emit(self.folder, n)
