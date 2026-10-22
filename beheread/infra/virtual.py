"""Tomes virtuels : plusieurs chapitres regroupes et lus comme un seul tome,
sans toucher aux fichiers.

Un tome virtuel a un chemin synthetique, « beheread-virtual:<id>/<Serie> -
Tome <n>.cbz » : son nom se lit comme celui d'un fichier ordinaire (serie,
numero : voir series.parse_path), ce qui le range dans sa serie, et sert de
cle a sa progression. Archive(chemin) l'ouvre en VirtualArchive, qui
enchaine les pages de ses chapitres ; la bibliotheque tient a jour la liste
des chapitres de chaque tome virtuel (`registry`).
"""

import threading
import uuid

from beheread.i18n import tr

PREFIX = "beheread-virtual:"


def is_virtual(path) -> bool:
    return isinstance(path, str) and path.startswith(PREFIX)


def make_path(volume_id: str, series_name: str, number) -> str:
    """Chemin synthetique d'un tome virtuel (voir le module)."""
    name = series_name.replace("/", " ").replace("\\", " ").strip()
    return f"{PREFIX}{volume_id}/{name} - Tome {number}.cbz"


def new_id() -> str:
    return uuid.uuid4().hex


def volume_id(path: str) -> str:
    """Identifiant du tome virtuel de ce chemin."""
    return path[len(PREFIX):].split("/", 1)[0]


class Registry:
    """Chapitres (chemins, dans l'ordre de lecture) de chaque tome virtuel,
    pour toute l'application (Archive, vignettes, lecteur). Thread-safe."""

    def __init__(self):
        self._lock = threading.Lock()
        self._chapters = {}   # chemin du tome virtuel -> [chemins des chapitres]

    def set_all(self, chapters_by_path: dict):
        with self._lock:
            self._chapters = {p: list(c) for p, c in chapters_by_path.items()}

    def chapters(self, path: str) -> list:
        with self._lock:
            return list(self._chapters.get(path, ()))


registry = Registry()


class VirtualArchive:
    """Tome virtuel, avec l'interface d'Archive : les pages de ses chapitres
    a la suite. `spans` : (premiere page, derniere page, chemin) de chaque
    chapitre, pour reporter la progression sur les chapitres lus."""

    def __init__(self, path: str, chapters=None):
        from beheread.infra.archive import Archive, ArchiveError
        self.path = path
        self.closed = False
        chapters = registry.chapters(path) if chapters is None else list(chapters)
        if not chapters:
            raise ArchiveError(tr("Ce tome virtuel n'a plus de chapitre."))
        self._parts = []
        try:
            for chapter in chapters:
                self._parts.append(Archive(chapter))
        except Exception:
            self.close()
            raise
        self.pages = []   # (indice de l'archive, page dans l'archive)
        self.spans = []
        for i, (part, chapter) in enumerate(zip(self._parts, chapters, strict=True)):
            first = len(self.pages)
            self.pages.extend((i, k) for k in range(len(part)))
            self.spans.append((first, len(self.pages) - 1, chapter))

    def __len__(self):
        return len(self.pages)

    def read_page(self, index: int) -> bytes:
        part, page = self.pages[index]
        return self._parts[part].read_page(page)

    def read_first_page(self) -> bytes:
        return self.read_page(0)

    def read_image(self, index: int, max_height: int = 0):
        part, page = self.pages[index]
        return self._parts[part].read_image(page, max_height)

    def read_comicinfo(self):
        return None

    def prepare_reading(self):
        for part in self._parts:
            part.prepare_reading()

    def chapter_at(self, index: int):
        """Chemin du chapitre qui contient la page `index`."""
        for first, last, chapter in self.spans:
            if first <= index <= last:
                return chapter
        return None

    def close(self):
        self.closed = True
        for part in self._parts:
            part.close()


def chapters_read(spans, page: int, finished: bool) -> list:
    """Chapitres lus en entier d'un tome virtuel lu jusqu'a la page `page`
    (tous s'il est termine)."""
    return [chapter for _first, last, chapter in spans if finished or page > last]

