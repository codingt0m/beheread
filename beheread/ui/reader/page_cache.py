"""Cache des pages decodees du lecteur : prechargement des pages voisines en
arriere-plan et eviction des plus anciennes (memoire bornee)."""

from PySide6.QtCore import QObject, QThread, QThreadPool, Signal

from beheread.ui.reader.components import PageLoader
from beheread.ui.reader.constants import CACHE_LIMIT, PRELOAD_RADIUS

# priorite des taches du pool du lecteur : la page demandee passe avant ses
# voisines, et les apercus de la barre de defilement apres tout le reste
PREVIEW_PRIORITY = -100


def reader_thread_count() -> int:
    """Threads du pool du lecteur : la lecture dans l'archive est serialisee
    par son verrou, seul le decodage (et l'analyse) profite du parallelisme."""
    return max(2, min(4, QThread.idealThreadCount() // 2))


class PageCache(QObject):
    loaded = Signal(int)    # index d'une page qui vient d'etre decodee
    evicted = Signal(int)   # index d'une page retiree du cache

    def __init__(self, archive, total, parent=None):
        super().__init__(parent)
        self.archive = archive
        self.total = total
        self.images = {}        # index -> QImage (nulle si page illisible)
        self.analysis = {}      # index -> PageAnalysis (recadrage, Ambilight)
        self._order = []
        self._pending = set()
        self._loaders = {}      # index -> loader en vol (evite un GC premature)
        self._center = 0
        # pool propre au lecteur : les pages ne font jamais la queue derriere
        # les vignettes ou le scan de la bibliotheque (pool global de Qt)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(reader_thread_count())

    def is_pending(self, index) -> bool:
        return index in self._pending

    def ensure_around(self, page):
        """Demande le decodage de `page` et de ses voisines (la plus proche
        d'abord, y compris devant des voisines demandees plus tot)."""
        self._center = page
        wanted = [i for i in range(page - PRELOAD_RADIUS, page + PRELOAD_RADIUS + 2)
                  if 0 <= i < self.total]
        for rank, i in enumerate(sorted(wanted, key=lambda x: abs(x - page))):
            if i not in self.images and i not in self._pending:
                self._pending.add(i)
                loader = PageLoader(self.archive, i, analyze=True)
                loader.signals.loaded.connect(self._on_loaded)
                self._loaders[i] = loader
                self.pool.start(loader, -rank)

    def start_preview(self, loader):
        """Apercu de la barre de defilement : meme pool, priorite minimale."""
        self.pool.start(loader, PREVIEW_PRIORITY)

    def shutdown(self):
        """Fermeture du lecteur : abandonne les decodages encore en file
        (ceux en cours se terminent, voir ArchiveClosedError)."""
        self.pool.clear()

    def _on_loaded(self, index, image, analysis=None):
        self._pending.discard(index)
        self._loaders.pop(index, None)
        self.images[index] = image
        if analysis is not None:
            self.analysis[index] = analysis
        self._order.append(index)
        # evince les pages les plus anciennes hors du voisinage de la page
        # courante ; celles du voisinage restent suivies dans _order (sans quoi
        # elles ne seraient plus jamais evincees et le cache grossirait sans fin)
        excess = len(self._order) - CACHE_LIMIT
        if excess > 0:
            far = [i for i in self._order if abs(i - self._center) > PRELOAD_RADIUS]
            for old in far[:excess]:
                self._order.remove(old)
                self.analysis.pop(old, None)
                if self.images.pop(old, None) is not None:
                    self.evicted.emit(old)
        self.loaded.emit(index)
