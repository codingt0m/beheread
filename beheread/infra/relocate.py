"""Deplacement de fichiers de la bibliotheque d'un dossier source a un autre
(ex. du disque local vers iCloud Drive).

Un fichier garde son sous-dossier : « D:/Mangas/Chainsaw Man/T01.cbz »
deplace vers « iCloud/Mangas » devient « iCloud/Mangas/Chainsaw Man/T01.cbz ».
La progression, les couvertures choisies, les tomes virtuels... sont indexes
par contenu (voir Store.key_for) : ils suivent le fichier.
"""

import errno
import os
import shutil
from pathlib import Path

from beheread.infra.storage import is_cloud_placeholder

MOVED, EXISTS, BUSY = "moved", "exists", "busy"
_CHUNK = 1024 * 1024


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def source_root(path, sources):
    """Dossier source (le plus profond) qui contient `path`, ou None."""
    p = _norm(path)
    best = None
    for src in sources:
        s = _norm(src)
        if p.startswith(s.rstrip("\\/") + os.sep) and (best is None or len(s) > len(_norm(best))):
            best = src
    return best


def destination(path, sources, dest) -> Path:
    """Chemin du fichier une fois deplace dans le dossier source `dest`, son
    sous-dossier conserve (a la racine de `dest` s'il n'est dans aucun
    dossier source)."""
    root = source_root(path, sources)
    rel = Path(os.path.relpath(path, root)) if root else Path(Path(path).name)
    return Path(dest) / rel


def plan(paths, sources, dest) -> list:
    """[(source, destination)] des fichiers a deplacer vers `dest` ; ceux
    qui y sont deja sont ignores."""
    out = []
    for path in dict.fromkeys(paths):
        if source_root(path, sources) is not None and \
                _norm(source_root(path, sources)) == _norm(dest):
            continue
        out.append((str(path), str(destination(path, sources, dest))))
    return out


def _hydrate(path):
    """Fichier cloud non telecharge (iCloud Drive, OneDrive) : le lire en
    entier le fait telecharger par le fournisseur avant le deplacement."""
    with open(path, "rb") as f:
        while f.read(_CHUNK):
            pass


def _busy(error: OSError) -> bool:
    """Fichier tenu par un autre programme (ouvert dans le lecteur...)."""
    return getattr(error, "winerror", None) == 32 or error.errno in (errno.EBUSY, errno.EACCES)


def move(src, dst) -> str:
    """Deplace un fichier : MOVED, EXISTS (un fichier porte deja ce nom a
    destination : rien n'est touche) ou BUSY (fichier ouvert ailleurs, a
    retenter). Leve OSError pour les autres echecs. D'un disque a un autre,
    le fichier est copie (dates comprises) puis supprime."""
    dst_path = Path(dst)
    if dst_path.exists():
        return EXISTS
    try:
        if is_cloud_placeholder(src):
            _hydrate(src)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst_path))
    except OSError as e:
        if _busy(e):
            # copie partielle d'un deplacement entre disques : retiree
            if Path(src).exists() and dst_path.exists():
                dst_path.unlink(missing_ok=True)
            return BUSY
        raise
    return MOVED
