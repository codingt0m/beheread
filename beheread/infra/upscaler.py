"""Moteur d'upscaling des pages : Real-ESRGAN (modele AnimeVideo v3 x2),
dans sa version ncnn + Vulkan (realesrgan-ncnn-vulkan, licence BSD-3).

Le moteur est un executable embarque dans beheread/resources/upscaler/
(recupere au build par tools/fetch_upscaler.py, absent du depot). Il calcule
sur le GPU via Vulkan ; sans GPU compatible, l'upscaling est indisponible.

Chaque lancement du moteur coute plusieurs secondes (pilote graphique,
chargement du modele) : on lui confie un lot de pages a la fois (Batch), et
les pages produites sont recuperees au fil de l'eau, sans attendre la fin du
lot. Les pages ameliorees sont gardees sur le disque (DiskCache) : relire un
tome est instantane."""

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import NamedTuple

from beheread.config import resource_path
from beheread.core import upscale_plan

MODEL = "realesr-animevideov3"
ENGINE_NAME = "Real-ESRGAN AnimeVideo v3"
_EXE = "realesrgan-ncnn-vulkan" + (".exe" if sys.platform == "win32" else "")
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
# premier lancement : initialisation du pilote Vulkan et compilation des
# shaders, jusqu'a une dizaine de secondes sur un GPU integre
PROBE_TIMEOUT = 90
# fin d'un fichier PNG complet (bloc IEND) : la page est entierement ecrite
_PNG_END = b"IEND\xaeB`\x82"


def engine_dir() -> Path:
    return resource_path("upscaler")


def engine_path():
    """Executable du moteur, ou None s'il n'est pas embarque."""
    exe = engine_dir() / _EXE
    if not exe.is_file():
        return None
    if sys.platform != "win32" and not os.access(exe, os.X_OK):
        try:   # droit d'execution perdu a la copie (archive, installation)
            exe.chmod(exe.stat().st_mode | 0o755)
        except OSError:
            return None
    return exe


# Reglages du moteur, mesures sur un GPU integre (Adreno X1-85, Billy Bat) :
# une page calculee a la fois (-j chargement:calcul:ecriture = 1:1:2) rend
# la premiere page du lot en 2,8 s au lieu de 4,9 s (deux pages en parallele
# finissent ensemble) ; des tuiles de 400 px donnent le meilleur debit
# (2,0 s par page, contre 2,2 s avec le choix automatique). Un GPU qui
# manque de memoire pour ces tuiles retombe sur le choix automatique
# (tile=0, voir services/upscaling.py).
THREADS = "1:1:2"
TILE = 400


def command(exe, src, dst, tile=TILE):
    cmd = [str(exe), "-i", str(src), "-o", str(dst), "-n", MODEL,
           "-s", str(upscale_plan.MODEL_SCALE), "-f", "png",
           "-m", str(engine_dir() / "models"), "-j", THREADS]
    if tile:
        cmd += ["-t", str(tile)]
    return cmd


# ------------------------------------------------------------ disponibilite
class Probe(NamedTuple):
    ok: bool
    gpu: str = ""       # nom du GPU utilise (ex. « Qualcomm(R) Adreno(TM) X1-85 GPU »)
    reason: str = ""    # « engine » (moteur absent) | « gpu » (pas de GPU compatible)


def parse_gpu(stderr: str) -> str:
    """Nom du GPU 0 dans la sortie du moteur (« [0 Nom du GPU]  queueC=... »),
    celui qu'il utilise par defaut."""
    for line in stderr.splitlines():
        line = line.strip()
        if line.startswith("[0 ") and "]" in line:
            return line[3:line.index("]")].strip()
    return ""


def probe() -> Probe:
    """Essaie le moteur sur une petite image : verifie qu'il est embarque et
    qu'un GPU Vulkan compatible le fait tourner."""
    exe = engine_path()
    if exe is None:
        return Probe(False, reason="engine")
    from PySide6.QtGui import QColor, QImage
    work = Path(tempfile.mkdtemp(prefix="beheread-upscale-probe-"))
    try:
        src, dst = work / "in.png", work / "out.png"
        img = QImage(32, 32, QImage.Format_RGB32)
        img.fill(QColor("#808080"))
        img.save(str(src))
        try:
            done = subprocess.run(command(exe, src, dst), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                  timeout=PROBE_TIMEOUT, creationflags=_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            logging.warning("Moteur d'upscaling inutilisable", exc_info=True)
            return Probe(False, reason="gpu")
        err = done.stderr.decode("utf-8", "replace")
        out = QImage(str(dst))
        if done.returncode != 0 or out.width() != 32 * upscale_plan.MODEL_SCALE:
            logging.warning("Upscaling indisponible (code %s) : %s", done.returncode, err[-500:])
            return Probe(False, reason="gpu")
        return Probe(True, gpu=parse_gpu(err))
    finally:
        shutil.rmtree(work, ignore_errors=True)


_probe_lock = threading.Lock()
_probe_result = None


def cached_probe() -> Probe:
    """probe(), fait une seule fois par session (bloquant : a appeler hors
    du thread de l'interface). Sert aux preferences ; le lecteur, lui,
    n'attend pas cet essai (voir services/upscaling.py)."""
    global _probe_result
    with _probe_lock:
        if _probe_result is None:
            _probe_result = probe()
        return _probe_result


def known_probe():
    """Resultat de cached_probe() s'il est deja connu, sinon None."""
    return _probe_result


def note_failure(reason="gpu"):
    """Le moteur a echoue dans le lecteur : indisponible pour la session
    (les preferences l'affichent sans refaire d'essai)."""
    global _probe_result
    with _probe_lock:
        _probe_result = Probe(False, reason=reason)


# ------------------------------------------------------------ lot de pages
def image_ext(data: bytes):
    """Extension d'un format que le moteur lit directement, ou None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class Batch:
    """Un lancement du moteur sur un lot de pages [(index, octets, ext)],
    traitees dans l'ordre du lot. poll() rend les pages terminees depuis le
    dernier appel ; le lot se nettoie seul (cleanup) une fois fini ou annule."""

    def __init__(self, jobs, tile=TILE):
        self.jobs = list(jobs)
        self.tile = tile
        self.order = [index for index, _data, _ext in self.jobs]
        self.pending = set(self.order)
        self.produced = 0       # pages rendues par le moteur
        self.started = 0.0
        self._work = None
        self._proc = None
        self._names = {}     # nom de sortie -> index
        self._log = None
        self.returncode = None

    def start(self, exe):
        self._work = Path(tempfile.mkdtemp(prefix="beheread-upscale-"))
        src, dst = self._work / "in", self._work / "out"
        src.mkdir()
        dst.mkdir()
        for rank, (index, data, ext) in enumerate(self.jobs):
            stem = f"{rank:03d}_{index}"
            (src / f"{stem}.{ext}").write_bytes(data)
            self._names[f"{stem}.png"] = index
        self._log = open(self._work / "engine.log", "wb")   # ferme par cleanup()
        self.started = time.monotonic()
        self._proc = subprocess.Popen(command(exe, src, dst, self.tile),
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=self._log, creationflags=_NO_WINDOW)
        return self

    def queued_before(self, index) -> int:
        """Pages encore a calculer avant `index` dans ce lot (le moteur les
        traite dans l'ordre du lot, une a la fois)."""
        count = 0
        for i in self.order:
            if i == index:
                return count
            if i in self.pending:
                count += 1
        return count

    @property
    def finished(self) -> bool:
        return self._proc is None or self.returncode is not None

    def poll(self):
        """[(index, chemin du PNG produit)] des pages terminees depuis le
        dernier appel."""
        if self._proc is None:
            return []
        if self.returncode is None:
            self.returncode = self._proc.poll()
        exited = self.returncode is not None
        done = []
        out = self._work / "out"
        for name, index in self._names.items():
            if index not in self.pending:
                continue
            path = out / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            # page complete : la fin du PNG (bloc IEND, ecrit en dernier) est
            # sur le disque - reprise des l'ecriture finie, sans attendre
            if exited or (size and _png_complete(path)):
                self.pending.discard(index)
                self.produced += 1
                done.append((index, path))
        return done

    def engine_log(self) -> str:
        try:
            return (self._work / "engine.log").read_text("utf-8", "replace")[-800:]
        except (OSError, TypeError):
            return ""

    def cancel(self):
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            try:
                self._proc.wait(timeout=5)
            except subprocess.SubprocessError:
                pass
        self.returncode = self._proc.returncode if self._proc is not None else -1

    def cleanup(self):
        self.cancel()
        if self._log is not None:
            self._log.close()
            self._log = None
        if self._work is not None:
            shutil.rmtree(self._work, ignore_errors=True)
            self._work = None


def _png_complete(path) -> bool:
    try:
        with open(path, "rb") as f:
            f.seek(-len(_PNG_END), os.SEEK_END)
            return f.read() == _PNG_END
    except OSError:
        return False


def purge_stale_work():
    """Dossiers de travail laisses par une session interrompue (plantage,
    arret brutal) : supprimes au premier usage."""
    root = Path(tempfile.gettempdir())
    for d in root.glob("beheread-upscale-*"):
        try:
            if time.time() - d.stat().st_mtime > 3600:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


# ------------------------------------------------------------ cache disque
class DiskCache:
    """Pages ameliorees gardees sur le disque, par tome (cle de contenu) et
    par page ; plafonne a CACHE_LIMIT_BYTES, les moins recemment lues
    partent d'abord."""

    def __init__(self, root: Path, limit: int = upscale_plan.CACHE_LIMIT_BYTES):
        self.root = Path(root)
        self.limit = limit
        self._lock = threading.Lock()

    def _dir(self, volume_key: str) -> Path:
        digest = hashlib.sha1(volume_key.encode("utf-8")).hexdigest()[:20]
        return self.root / digest

    def _paths(self, volume_key, index):
        d = self._dir(volume_key)
        return d / f"{index:05d}.png", d / f"{index:05d}.jpg"

    def load(self, volume_key, index):
        """Page amelioree (QImage) ou None."""
        from PySide6.QtGui import QImage
        for path in self._paths(volume_key, index):
            if path.is_file():
                img = QImage(str(path))
                if img.isNull():
                    path.unlink(missing_ok=True)
                    return None
                try:
                    os.utime(path)   # date d'acces : base de l'eviction
                except OSError:
                    pass
                return img
        return None

    def save(self, volume_key, index, img):
        """Niveaux de gris en PNG (sans perte, et compact pour du noir et
        blanc), couleur en JPEG de haute qualite."""
        from PySide6.QtGui import QImage
        png, jpg = self._paths(volume_key, index)
        png.parent.mkdir(parents=True, exist_ok=True)
        gray = img.format() == QImage.Format_Grayscale8
        target = png if gray else jpg
        tmp = target.with_suffix(".part")
        if not img.save(str(tmp), "PNG" if gray else "JPEG", -1 if gray else 94):
            tmp.unlink(missing_ok=True)
            return
        os.replace(tmp, target)
        self.trim()

    def _files(self):
        files = []
        if not self.root.is_dir():
            return files
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            for f in d.iterdir():
                try:
                    st = f.stat()
                except OSError:
                    continue
                files.append((str(f), st.st_size, st.st_mtime))
        return files

    def size(self) -> int:
        return sum(size for _p, size, _m in self._files())

    def trim(self):
        with self._lock:
            for path in upscale_plan.files_to_evict(self._files(), self.limit):
                Path(path).unlink(missing_ok=True)

    def clear(self) -> int:
        """Vide le cache ; rend le nombre d'octets liberes."""
        with self._lock:
            freed = self.size()
            shutil.rmtree(self.root, ignore_errors=True)
            return freed


def default_cache() -> DiskCache:
    from beheread.infra.storage import data_dir
    return DiskCache(data_dir() / "upscaled")
