"""Lecture des archives CBZ (ZIP), CBR (RAR), EPUB et des PDF directement en
memoire, sans extraction permanente sur le disque.

Un PDF n'est pas une archive d'images : ses pages sont rendues a la demande
(module QtPdf, fourni avec PySide6) par PdfArchive, qui expose la meme
interface. `Archive(chemin)` choisit automatiquement la bonne classe.

Un EPUB etant lui-meme un conteneur ZIP, il est traite comme un CBZ : les
images qu'il contient sont listees et triees comme des pages de manga (utile
pour les scans distribues au format EPUB a mise en page fixe). Un EPUB de
roman purement textuel, sans images, ne contiendra donc aucune page.

Le format reel est detecte par la signature du fichier (certains .cbr sont en
realite des ZIP renommes, et inversement).

Pour les vrais RAR, la bibliotheque `rarfile` est utilisee. Elle s'appuie sur
un outil externe : UnRAR.exe (fourni gratuitement par RARLab ou installe avec
WinRAR), ou a defaut 7-Zip (detecte dans Program Files ou via le PATH) / bsdtar.
Voir README.md pour l'installation.
"""

import logging
import os
import re
import sys
import threading
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
SUPPORTED_EXTS = {".cbz", ".cbr", ".zip", ".rar", ".epub", ".pdf"}

# Rendu des pages PDF : resolution visee, bornee pour rester net en plein
# ecran sans exploser la memoire (une page decodee en ARGB fait ~4 octets/px).
PDF_DPI = 200
PDF_MAX_SIDE = 3200
PDF_MIN_SIDE = 1400

# Garde-fou anti "bombe de decompression" : les archives proviennent de
# sources non fiables (telechargements). Un membre de quelques Ko peut se
# decompresser en plusieurs Go et epuiser la memoire. On refuse de lire une
# page dont la taille DECOMPRESSEE annoncee depasse ce plafond (200 Mo : tres
# au-dessus de toute page de scan legitime, meme en haute definition).
MAX_PAGE_BYTES = 200 * 1024 * 1024

# Meme logique pour ComicInfo.xml : un fichier de metadonnees legitime pese
# quelques Ko. Au-dela, on ignore (evite de charger un XML piege en memoire).
MAX_COMICINFO_BYTES = 4 * 1024 * 1024

# Une declaration DOCTYPE est le prerequis des attaques XML classiques
# (expansion d'entites facon "billion laughs", XXE). ComicInfo.xml n'en a
# jamais besoin ; dans un XML bien forme, la sequence "<!DOCTYPE" ne peut
# apparaitre que comme un vrai DOCTYPE dans le prologue. On rejette donc tout
# document qui en contient (defense en profondeur, sans dependance externe).
_DOCTYPE_RE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)

_rarfile = None
_rar_error = None


def _init_rarfile():
    """Importe rarfile et localise un outil UnRAR si possible."""
    global _rarfile, _rar_error
    if _rarfile is not None or _rar_error is not None:
        return
    try:
        import rarfile
    except ImportError:
        _rar_error = (
            "Le module Python « rarfile » n'est pas installé.\n"
            "Installez-le avec :  pip install rarfile"
        )
        return

    from beheread.config import app_root
    candidates = [app_root() / "unrar.exe", app_root() / "UnRAR.exe"]
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if base:
                candidates.append(Path(base) / "WinRAR" / "UnRAR.exe")
    for cand in candidates:
        try:
            if cand and cand.exists():
                rarfile.UNRAR_TOOL = str(cand)
                break
        except OSError:
            pass
    # 7-Zip installe a son emplacement standard : utilise en repli, sans
    # avoir a ajouter son dossier au PATH.
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if not base:
                continue
            seven = Path(base) / "7-Zip" / "7z.exe"
            try:
                if seven.exists():
                    rarfile.SEVENZIP_TOOL = str(seven)
                    break
            except OSError:
                pass
    _rarfile = rarfile


def _natural_key(name: str):
    """Tri naturel : page2 avant page10."""
    parts = re.split(r"(\d+)", name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def _detect_format(path: str) -> str:
    """Retourne 'zip', 'rar', 'pdf' ou 'unknown' d'apres la signature du fichier."""
    try:
        with open(path, "rb") as f:
            sig = f.read(8)
    except OSError:
        return "unknown"
    if sig.startswith(b"PK\x03\x04") or sig.startswith(b"PK\x05\x06"):
        return "zip"
    if sig.startswith(b"Rar!"):
        return "rar"
    if sig.startswith(b"%PDF"):
        return "pdf"
    return "unknown"


class ArchiveError(Exception):
    pass


class ArchiveClosedError(ArchiveError):
    """Lecture demandee sur une archive deja fermee (ex. prechargement encore
    en file quand le lecteur se ferme)."""


class Archive:
    """Acces uniforme a une archive CBZ/CBR/EPUB (ou, via PdfArchive, a un
    PDF). Thread-safe pour la lecture."""

    def __new__(cls, path: str):
        # un PDF est servi par PdfArchive (meme interface) : les appelants
        # continuent d'ecrire simplement Archive(chemin)
        if cls is Archive:
            fmt = _detect_format(path)
            if fmt == "pdf" or (fmt == "unknown" and Path(path).suffix.lower() == ".pdf"):
                return super().__new__(PdfArchive)
        return super().__new__(cls)

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.closed = False
        fmt = _detect_format(path)
        ext = Path(path).suffix.lower()

        if fmt == "zip" or (fmt == "unknown" and ext in (".cbz", ".zip", ".epub")):
            try:
                self._ar = zipfile.ZipFile(path)
            except zipfile.BadZipFile as e:
                raise ArchiveError(f"Archive ZIP invalide :\n{path}\n{e}")
        elif fmt == "rar" or (fmt == "unknown" and ext in (".cbr", ".rar")):
            _init_rarfile()
            if _rar_error:
                raise ArchiveError(_rar_error)
            try:
                self._ar = _rarfile.RarFile(path)
            except _rarfile.RarCannotExec as e:
                raise ArchiveError(
                    "Aucun outil de décompression RAR n'a été trouvé.\n\n"
                    "Installez WinRAR ou 7-Zip, ou placez UnRAR.exe dans le "
                    "dossier de Beheread.\n"
                    "Voir le README, section « Lire les fichiers CBR ».\n\n"
                    f"Détail : {e}")
            except Exception as e:
                raise ArchiveError(f"Impossible d'ouvrir l'archive RAR :\n{path}\n{e}")
        else:
            raise ArchiveError(f"Format d'archive non reconnu :\n{path}")

        names = []
        for n in self._ar.namelist():
            p = Path(n)
            if p.suffix.lower() not in IMAGE_EXTS:
                continue
            if "__MACOSX" in p.parts or p.name.startswith("."):
                continue
            names.append(n)
        names.sort(key=_natural_key)
        if not names:
            self.close()
            raise ArchiveError(f"Aucune image trouvée dans l'archive :\n{path}")
        self.pages = names

    def __len__(self):
        return len(self.pages)

    def _guard_size(self, name: str, limit: int):
        """Refuse une entree dont la taille decompressee annoncee depasse
        `limit` (garde-fou anti bombe de decompression). La taille est lue dans
        l'en-tete de l'archive, sans rien decompresser."""
        try:
            info = self._ar.getinfo(name)
            size = getattr(info, "file_size", 0) or 0
        except Exception:
            size = 0   # en-tete illisible : on laisse la lecture tenter sa chance
        if size > limit:
            raise ArchiveError(
                f"Entrée anormalement volumineuse ignorée ({size} octets) :\n"
                f"{name}\ndans {self.path}")

    def read_page(self, index: int) -> bytes:
        name = self.pages[index]
        self._guard_size(name, MAX_PAGE_BYTES)
        with self._lock:
            if self.closed:
                # lecteur ferme pendant un prechargement : cas normal, pas une erreur
                raise ArchiveClosedError(self.path)
            return self._ar.read(name)

    def read_first_page(self) -> bytes:
        return self.read_page(0)

    def read_image(self, index: int, max_height: int = 0):
        """Page decodee (QImage, nulle si illisible). `max_height` n'est
        qu'une indication de taille utile, exploitee par le rendu PDF ; une
        image matricielle est toujours decodee en entier."""
        from PySide6.QtGui import QImage
        return QImage.fromData(self.read_page(index))

    def read_comicinfo(self):
        """Lit et parse ComicInfo.xml (standard ComicRack) a la racine de
        l'archive, s'il existe. Renvoie un dict ou None si absent/illisible.
        C'est la source de metadonnees prioritaire : locale, fiable, et
        100% hors ligne si l'utilisateur a tague ses fichiers."""
        try:
            names = self._ar.namelist()
        except Exception:
            logging.warning("Liste des fichiers illisible dans %s", self.path, exc_info=True)
            return None
        target = next((n for n in names if Path(n).name.lower() == "comicinfo.xml"), None)
        if target is None:
            return None
        try:
            self._guard_size(target, MAX_COMICINFO_BYTES)
            with self._lock:
                raw = self._ar.read(target)
            if _DOCTYPE_RE.search(raw):
                # DOCTYPE present : refus par principe (anti expansion d'entites
                # / XXE). Un ComicInfo.xml legitime n'en contient jamais.
                logging.warning("ComicInfo.xml avec DOCTYPE ignore (securite) dans %s",
                                self.path)
                return None
            root = ET.fromstring(raw)
        except Exception:
            # ComicInfo.xml present mais illisible/mal forme : la cascade de
            # metadonnees se rabat sur les sources reseau (voir metadata.py),
            # d'ou l'interet de tracer ce cas plutot que de le laisser muet.
            logging.warning("ComicInfo.xml illisible/invalide dans %s", self.path, exc_info=True)
            return None

        def text(tag):
            el = root.find(tag)
            return el.text.strip() if el is not None and el.text else None

        def integer(tag):
            v = text(tag)
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        # un seul auteur "principal" : premier champ renseigne (Writer en
        # priorite, le scenariste/mangaka), premier nom s'il y en a plusieurs
        authors = []
        for tag in ("Writer", "Penciller", "Author"):
            v = text(tag)
            if v:
                first = v.split(",")[0].strip()
                if first:
                    authors = [first]
                break

        # champ "Manga" standard ComicRack : seule la valeur explicite
        # "YesAndRightToLeft" garantit un sens de lecture ("Yes" seul ne fait
        # que signaler un manga sans preciser le sens, "No" un sens occidental)
        manga = text("Manga")
        if manga and manga.strip().lower() == "yesandrighttoleft":
            reading_direction = "rtl"
        elif manga and manga.strip().lower() == "no":
            reading_direction = "ltr"
        else:
            reading_direction = None

        return {
            "series": text("Series"),
            "title": text("Title"),
            "number": integer("Number") or integer("Volume"),
            "year": integer("Year"),
            "month": integer("Month"),
            "day": integer("Day"),
            "publisher": text("Publisher"),
            "authors": authors,
            "reading_direction": reading_direction,
        }

    def close(self):
        """Ferme l'archive. Prend le verrou de lecture : une page en cours de
        decompression dans un thread de prechargement se termine d'abord, au
        lieu de voir son fichier ferme en pleine lecture. Idempotent."""
        with self._lock:
            if self.closed:
                return
            self.closed = True
            try:
                self._ar.close()
            except Exception:
                logging.debug("Fermeture d'archive en echec : %s", self.path, exc_info=True)


class PdfArchive(Archive):
    """Document PDF vu comme une suite de pages-images, rendues a la demande
    par QtPdf (PDFium). Le rendu est serialise par le verrou de l'archive (et
    par le verrou global de QtPdf) : il peut etre appele depuis les threads de
    prechargement."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.closed = False
        try:
            from PySide6.QtPdf import QPdfDocument
        except ImportError:
            raise ArchiveError("La lecture des PDF nécessite le module QtPdf "
                               "(PySide6-Addons), introuvable.")
        self._doc = QPdfDocument()
        err = self._doc.load(path)
        if err != QPdfDocument.Error.None_:
            name = getattr(err, "name", str(err))
            self._doc.close()
            if name == "IncorrectPassword":
                raise ArchiveError(f"PDF protégé par un mot de passe :\n{path}")
            raise ArchiveError(f"PDF illisible ({name}) :\n{path}")
        count = self._doc.pageCount()
        if count <= 0:
            self._doc.close()
            raise ArchiveError(f"Aucune page dans le PDF :\n{path}")
        self.pages = [f"page {i + 1}" for i in range(count)]

    def _render_size(self, index: int, max_height: int):
        from PySide6.QtCore import QSize
        pts = self._doc.pagePointSize(index)
        w, h = max(1.0, pts.width()), max(1.0, pts.height())
        scale = PDF_DPI / 72.0
        longest = max(w, h) * scale
        if longest > PDF_MAX_SIDE:
            scale *= PDF_MAX_SIDE / longest
        elif longest < PDF_MIN_SIDE:
            scale *= PDF_MIN_SIDE / longest
        if max_height and h * scale > max_height:
            scale = max_height / h
        return QSize(max(1, round(w * scale)), max(1, round(h * scale)))

    def read_image(self, index: int, max_height: int = 0):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPainter
        with self._lock:
            if self.closed:
                raise ArchiveClosedError(self.path)
            size = self._render_size(index, max_height)
            rendered = self._doc.render(index, size)
        if rendered.isNull():
            return rendered
        # PDFium rend un fond transparent : on compose sur du blanc, sinon le
        # texte d'une page sans fond apparaitrait sur le fond noir du lecteur
        page = QImage(rendered.size(), QImage.Format_RGB32)
        page.fill(Qt.white)
        painter = QPainter(page)
        painter.drawImage(0, 0, rendered)
        painter.end()
        return page

    def read_page(self, index: int) -> bytes:
        """Page rendue et encodee en PNG (compatibilite ; preferer read_image)."""
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.WriteOnly)
        self.read_image(index).save(buf, "PNG")
        return bytes(data)

    def read_comicinfo(self):
        return None   # pas de ComicInfo.xml dans un PDF

    def close(self):
        with self._lock:
            if self.closed:
                return
            self.closed = True
            try:
                self._doc.close()
            except Exception:
                logging.debug("Fermeture de PDF en echec : %s", self.path, exc_info=True)


def find_next_volume(path: str):
    """Tome suivant de la meme serie dans le dossier de `path`, ou None."""
    from beheread.core.series import next_volume
    return next_volume(path, scan_folder(str(Path(path).parent)))


def scan_folder(folder: str):
    """Liste recursivement les fichiers CBZ/CBR/EPUB/PDF d'un dossier."""
    root = Path(folder)
    if not root.is_dir():
        return []
    # On filtre AVANT de trier : le tri naturel (regex par element) ne
    # s'applique qu'aux archives retenues, pas a tous les fichiers/dossiers
    # traverses (images, ComicInfo.xml, sous-repertoires...).
    matches = [p for p in root.rglob("*")
               if p.suffix.lower() in SUPPORTED_EXTS and p.is_file()]
    matches.sort(key=lambda x: _natural_key(str(x)))
    return [str(p) for p in matches]
