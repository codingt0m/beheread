"""Cache des pages decodees du lecteur : prechargement des pages voisines en
arriere-plan et eviction des plus anciennes (memoire bornee)."""

from PySide6.QtCore import QObject, QThreadPool, Signal

from beheread.ui.reader.components import PageLoader
from beheread.ui.reader.constants import CACHE_LIMIT, PRELOAD_RADIUS


class PageCache(QObject):
    loaded = Signal(int)    # index d'une page qui vient d'etre decodee
    evicted = Signal(int)   # index d'une page retiree du cache

    def __init__(self, archive, total, parent=None):
        super().__init__(parent)
        self.archive = archive
        self.total = total
        self.images = {}        # index -> QImage (nulle si page illisible)
        self._order = []
        self._pending = set()
        self._loaders = {}      # index -> loader en vol (evite un GC premature)
        self._center = 0
        self.pool = QThreadPool.globalInstance()

    def is_pending(self, index) -> bool:
        return index in self._pending

    def ensure_around(self, page):
        """Demande le decodage de `page` et de ses voisines (la plus proche
        d'abord)."""
        self._center = page
        wanted = [i for i in range(page - PRELOAD_RADIUS, page + PRELOAD_RADIUS + 2)
                  if 0 <= i < self.total]
        for i in sorted(wanted, key=lambda x: abs(x - page)):
            if i not in self.images and i not in self._pending:
                self._pending.add(i)
                loader = PageLoader(self.archive, i)
                loader.signals.loaded.connect(self._on_loaded)
                self._loaders[i] = loader
                self.pool.start(loader)

    def _on_loaded(self, index, image):
        self._pending.discard(index)
        self._loaders.pop(index, None)
        self.images[index] = image
        self._order.append(index)
        # evince les pages les plus anciennes hors du voisinage de la page
        # courante ; celles du voisinage restent suivies dans _order (sans quoi
        # elles ne seraient plus jamais evincees et le cache grossirait sans fin)
        excess = len(self._order) - CACHE_LIMIT
        if excess > 0:
            far = [i for i in self._order if abs(i - self._center) > PRELOAD_RADIUS]
            for old in far[:excess]:
                self._order.remove(old)
                if self.images.pop(old, None) is not None:
                    self.evicted.emit(old)
        self.loaded.emit(index)
