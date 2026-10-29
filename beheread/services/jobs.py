"""Taches de fond des services (requetes reseau, telechargements) : une
fonction executee dans un QThreadPool, dont le resultat revient sur le
thread UI par un signal."""

from PySide6.QtCore import QObject, QRunnable, Signal


class _Signals(QObject):
    done = Signal(object, object)   # resultat, exception (ou None)


class Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn()
        except Exception as e:   # erreur reseau ou reponse inattendue : rapportee
            self.signals.done.emit(None, e)
            return
        self.signals.done.emit(result, None)


class JobRunner:
    """Lance des Job dans un pool et en garde la reference jusqu'a leur fin
    (sans quoi le ramasse-miettes peut detruire les signaux en vol)."""

    def __init__(self, pool):
        self.pool = pool
        self._jobs = set()

    def run(self, fn, callback):
        """callback(resultat, exception ou None), appele sur le thread UI."""
        job = Job(fn)
        self._jobs.add(job)

        def done(result, err, job=job):
            self._jobs.discard(job)
            callback(result, err)
        job.signals.done.connect(done)
        self.pool.start(job)
