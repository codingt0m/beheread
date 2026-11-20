"""Upscaling des pages d'un tome ouvert dans le lecteur, en tache de fond.

Le lecteur indique les pages affichees (want) ; le service prepare celles-ci
puis les suivantes (core/upscale_plan.py) et rend chaque page amelioree par
le signal `ready`, a la taille d'affichage. Il tourne dans son propre thread :
lecture des pages dans l'archive, lancement du moteur (infra/upscaler.py),
reprise des pages produites, cache disque. Le thread de l'interface ne fait
qu'afficher ce qui arrive."""

import logging
import threading

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSize, Qt, Signal
from PySide6.QtGui import QImage, QImageReader

from beheread.core import upscale_plan
from beheread.infra import upscaler
from beheread.infra.archive import ArchiveClosedError

POLL_S = 0.05   # intervalle de reprise des pages produites par le moteur
# relance du moteur sur la page affichee quand au moins ce nombre de pages
# la precedent encore dans le lot en cours (voir _should_restart)
RESTART_QUEUE = 2
_GRAY_FORMATS = (QImage.Format_Grayscale8, QImage.Format_Grayscale16, QImage.Format_Mono,
                 QImage.Format_MonoLSB)
_RGB_FORMATS = (QImage.Format_RGB32, QImage.Format_ARGB32, QImage.Format_RGB888,
                QImage.Format_ARGB32_Premultiplied)


def _header(data):
    """(taille, format) d'une image d'apres son en-tete, sans la decoder."""
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.ReadOnly)
    reader = QImageReader(buf)
    return reader.size(), reader.imageFormat()


def _png_bytes(img):
    out = QByteArray()
    buf = QBuffer(out)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(out)


def hold_window(current, total):
    """Pages ameliorees que le lecteur garde en memoire : celles que le
    service prepare d'avance (voir upscale_plan.next_batch)."""
    return upscale_plan.preparation_order(current, total, 2 * upscale_plan.AHEAD,
                                          upscale_plan.BEHIND)


class UpscaleService(QObject):
    ready = Signal(int, QImage)   # page amelioree, a sa taille d'affichage
    skipped = Signal(int)         # page sans besoin d'amelioration, ou illisible
    unavailable = Signal(str)     # « engine » | « gpu » : moteur inutilisable

    def __init__(self, archive, volume_key, cache=None, parent=None):
        super().__init__(parent)
        self.archive = archive
        self.volume_key = volume_key
        self.cache = cache if cache is not None else upscaler.default_cache()
        self._cond = threading.Condition()
        self._current = []        # pages affichees
        self._have = set()        # pages deja ameliorees, tenues par le lecteur
        self._screen = (0, 0)     # pixels physiques de l'ecran
        self._fit_width = False
        self._stopped = False
        self._changed = False
        self._skipped = set()     # pages sans besoin d'amelioration (pour cet ecran)
        self._sent = set()        # pages rendues depuis le dernier want()
        self._meta = {}           # index -> (largeur, hauteur, gris, gain) de la source
        self._batch = None
        self._tile = upscaler.TILE    # 0 apres un echec : choix automatique du moteur
        # demarre a la premiere demande (want) : le lecteur a branche ses
        # signaux, aucun message (« indisponible ») ne se perd
        self._thread = threading.Thread(target=self._run, name="beheread-upscale", daemon=True)

    # ----- appele par le lecteur (thread de l'interface) -----
    def want(self, current, have, screen, fit_width):
        """Pages affichees `current`, pages ameliorees que le lecteur a deja
        (`have`), taille physique de l'ecran et ajustement."""
        with self._cond:
            if (tuple(screen), bool(fit_width)) != (self._screen, self._fit_width):
                self._skipped.clear()   # le besoin depend de la taille d'affichage
            self._current = list(current)
            self._have = set(have)
            # le lecteur oublie les pages sorties de cette fenetre : elles
            # seront rendues a nouveau (depuis le disque) si on y revient
            self._sent &= set(hold_window(self._current, len(self.archive)))
            self._screen = tuple(screen)
            self._fit_width = bool(fit_width)
            self._changed = True
            self._cond.notify()
        if not self._thread.is_alive() and not self._thread.ident:
            self._thread.start()

    def stop(self):
        """Arret du service (fermeture du lecteur) : le lot en cours est
        abandonne. N'attend pas la fin du thread, qui ne touche plus au
        lecteur une fois arrete."""
        with self._cond:
            self._stopped = True
            self._cond.notify()

    def join(self, timeout=None):
        if self._thread.ident:
            self._thread.join(timeout)

    # ----- thread du service -----
    def _run(self):
        # pas d'essai prealable du moteur (une seconde de plus avant la
        # premiere page) : le premier lot en tient lieu, et seul son echec
        # rend l'upscaling indisponible
        known = upscaler.known_probe()
        exe = upscaler.engine_path()
        if exe is None or (known is not None and not known.ok):
            if not self._is_stopped():
                self.unavailable.emit("engine" if exe is None else known.reason)
            return
        upscaler.purge_stale_work()
        try:
            while True:
                with self._cond:
                    if not self._stopped and not self._changed and self._batch is None:
                        self._cond.wait()
                    elif not self._stopped and self._batch is not None:
                        self._cond.wait(POLL_S)
                    if self._stopped:
                        return
                    self._changed = False
                    current = list(self._current)
                    ready = self._have | self._sent | self._skipped
                    screen, fit_width = self._screen, self._fit_width
                self._step(exe, current, ready, screen, fit_width)
        except ArchiveClosedError:
            return   # lecteur ferme entre-temps
        except Exception:
            logging.exception("Upscaling interrompu")
        finally:
            if self._batch is not None:
                self._batch.cleanup()
                self._batch = None

    def _is_stopped(self):
        with self._cond:
            return self._stopped

    def _step(self, exe, current, ready, screen, fit_width):
        batch = self._batch
        if batch is not None and self._should_restart(batch, current, ready):
            batch.cleanup()
            self._batch = batch = None
        if batch is not None:
            for index, path in batch.poll():
                self._finish(index, path)
            if batch.finished:
                self._batch_done(batch)
                batch.cleanup()
                self._batch = None
                with self._cond:
                    self._changed = True   # de quoi lancer le lot suivant
            return
        jobs = []
        for index in upscale_plan.next_batch(current, len(self.archive), ready):
            if self._is_stopped():
                return
            job = self._prepare(index, screen, fit_width)
            if job is not None:
                jobs.append(job)
        if jobs:
            self._batch = upscaler.Batch(jobs, self._tile).start(exe)

    @staticmethod
    def _should_restart(batch, current, ready):
        """Une page affichee attend sans etre en tete du lot : apres un saut
        (elle n'y est pas), ou quand la lecture va plus vite que le moteur
        (des pages passees la precedent). Relancer le moteur sur elle coute
        moins d'une seconde de demarrage, attendre coute deux secondes par
        page devant elle."""
        waiting = [i for i in current if i not in ready]
        if not waiting:
            return False
        queued = [batch.queued_before(i) for i in waiting if i in batch.pending]
        return not queued or min(queued) >= RESTART_QUEUE

    def _batch_done(self, batch):
        """Fin d'un lot : un echec sans aucune page produite vient du GPU
        (pilote, memoire). Premier recours : le choix automatique des tuiles ;
        ensuite, l'upscaling est indisponible pour la session."""
        if batch.returncode == 0 or not batch.pending:
            return
        logging.warning("Moteur d'upscaling en echec (code %s, tuiles %s) : %s",
                        batch.returncode, batch.tile or "auto", batch.engine_log())
        if batch.produced == 0 and self._tile:
            self._tile = 0   # les pages en attente repartent au prochain lot
            return
        if batch.produced == 0:
            upscaler.note_failure("gpu")
            with self._cond:
                self._stopped = True
            self.unavailable.emit("gpu")
            return
        for index in batch.pending:   # page qui fait echouer le moteur : abandonnee
            self._mark_skipped(index)

    def _prepare(self, index, screen, fit_width):
        """Page `index` a confier au moteur (index, octets, ext), ou None :
        deja dans le cache disque (rendue tout de suite), sans besoin
        d'amelioration, ou illisible. Seul l'en-tete de l'image est lu
        (taille, niveaux de gris) : le moteur demarre sans attendre le
        decodage de tout le lot."""
        cached = self.cache.load(self.volume_key, index)
        if cached is not None:
            self._send(index, cached)
            return None
        try:
            data = self.archive.read_page(index)
        except ArchiveClosedError:
            raise
        except Exception:
            logging.warning("Page %d illisible pour l'upscaling", index, exc_info=True)
            self._mark_skipped(index)
            return None
        size, fmt = _header(data)
        gain = upscale_plan.display_gain(size.width(), size.height(), *screen, fit_width)
        if not upscale_plan.needs_upscale(gain):
            self._mark_skipped(index)
            return None
        ext = upscaler.image_ext(data)
        if ext is None:   # format que le moteur ne lit pas : reencode en PNG
            src = QImage.fromData(data)
            if src.isNull():
                self._mark_skipped(index)
                return None
            data, ext = _png_bytes(src), "png"
        self._meta[index] = (size.width(), size.height(), fmt, gain, data)
        return index, data, ext

    def _finish(self, index, path):
        """Page produite par le moteur : ramenee a sa taille d'affichage, en
        niveaux de gris si la source l'est (le modele, en couleur, y laisse
        sinon de legeres franges colorees), rendue au lecteur PUIS gardee sur
        le disque (l'ecriture ne retarde pas l'affichage)."""
        out = QImage(str(path))
        meta = self._meta.pop(index, None)
        if out.isNull() or meta is None:
            self._mark_skipped(index)
            return
        w, h, fmt, gain, data = meta
        gray = fmt in _GRAY_FORMATS
        if not gray and fmt in _RGB_FORMATS:
            # scan noir et blanc enregistre en couleur : seul le decodage le dit
            gray = QImage.fromData(data).isGrayscale()
        tw, th = upscale_plan.stored_size(w, h, gain)
        img = out.scaled(QSize(tw, th), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        img = img.convertToFormat(QImage.Format_Grayscale8 if gray else QImage.Format_RGB32)
        self._send(index, img)
        try:
            self.cache.save(self.volume_key, index, img)
        except OSError:
            logging.warning("Page amelioree non gardee sur le disque", exc_info=True)

    def _send(self, index, img):
        with self._cond:
            if self._stopped:
                return
            self._sent.add(index)
        self.ready.emit(index, img)

    def _mark_skipped(self, index):
        with self._cond:
            if self._stopped:
                return
            self._skipped.add(index)
        self.skipped.emit(index)
