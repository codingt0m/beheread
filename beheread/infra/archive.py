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
un outil externe, cherche par beheread.platforms.rar_tools : sous Windows
UnRAR.exe (fourni gratuitement par RARLab ou installe avec WinRAR), ou a
defaut 7-Zip ; sous macOS unrar ou 7-Zip s'ils sont installes, sinon bsdtar,
fourni avec le systeme. Voir README.md pour l'installation.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from beheread import platforms
from beheread.i18n import tr
from beheread.infra import safe_xml

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

# Recherche de l'ISBN en code-barres (voir Archive.find_isbn) : pages lues au
# plus, et hauteur de decodage maximale. Le code d'un ISBN mesure environ
# 37 mm : sur une page de 30 cm scannee a 2 400 pixels de haut, un module
# (barre la plus fine) fait 3 pixels - reduit davantage, il devient illisible
ISBN_SCAN_PAGES = 4
ISBN_SCAN_HEIGHT = 3200

_rarfile = None
_rar_error = None
_rar_tools = {}   # sorte d'outil RAR -> chemin absolu retenu (voir _init_rarfile)

# RAR « solide » : un fichier ne se decompresse qu'apres tout ce qui le
# precede. Lu page par page (un appel a l'outil par page), chaque page coute
# de plus en plus cher. Pour la lecture, toutes les pages sont extraites en
# une passe, en arriere-plan, dans un dossier temporaire supprime a la
# fermeture (voir Archive.prepare_reading).
SOLID_PREFIX = "beheread-rar-"
SOLID_MAX_BYTES = 4 * 1024 * 1024 * 1024   # au-dela : lecture page par page
SOLID_TIMEOUT = 600                        # secondes, extraction complete
SOLID_STALE_AGE = 24 * 3600                # dossiers laisses par un arret brutal

# sorte d'outil (beheread.platforms.rar_tools) -> reglage de rarfile
_RAR_TOOL_ATTRS = (("unrar", "UNRAR_TOOL"), ("sevenzip", "SEVENZIP_TOOL"),
                   ("bsdtar", "BSDTAR_TOOL"))


def _no_rar_tool(error) -> str:
    return (tr("Aucun outil de décompression RAR n'a été trouvé.") + "\n\n"
            + tr(platforms.RAR_HELP) + "\n"
            + tr("Voir le README, section « Lire les fichiers CBR ».") + "\n\n"
            + tr("Détail : {error}", error=error))


def _init_rarfile():
    """Importe rarfile et localise un outil UnRAR si possible."""
    global _rarfile, _rar_error
    if _rarfile is not None or _rar_error is not None:
        return
    try:
        import rarfile
    except ImportError:
        _rar_error = tr("Le module Python « rarfile » n'est pas installé.\n"
                        "Installez-le avec :  pip install rarfile")
        return

    from beheread.config import app_root
    # outils propres au systeme (voir beheread.platforms.rar_tools) : le
    # premier present de chaque sorte est retenu, rarfile essaie ensuite
    # unrar, puis 7-Zip et bsdtar.
    tools = platforms.rar_tools(app_root())
    found = set()
    for kind, attr in _RAR_TOOL_ATTRS:
        for cand in tools.get(kind, ()):
            try:
                if cand.is_absolute() and cand.exists():
                    setattr(rarfile, attr, str(cand))
                    found.add(kind)
                    _rar_tools[kind] = str(cand)
                    break
            except OSError:
                pass
    # Securite : rarfile ne lance QUE les outils trouves ci-dessus, par leur
    # chemin absolu. Ses valeurs par defaut ("unrar", "unar", "7zz"...) sont
    # des noms nus : sous Windows, ils sont cherches d'abord dans le dossier
    # courant, celui du fichier double-clique, ou un unrar.exe piege peut
    # avoir ete telecharge avec le CBR. La configuration retenue est memorisee
    # par rarfile pour toutes les ouvertures suivantes.
    try:
        rarfile.tool_setup(unrar="unrar" in found, unar=False,
                           sevenzip="sevenzip" in found, sevenzip2=False,
                           bsdtar="bsdtar" in found, force=True)
    except rarfile.RarCannotExec as e:
        _rar_error = _no_rar_tool(e)
        return
    _rarfile = rarfile


def _natural_key(name: str):
    """Tri naturel : page2 avant page10."""
    parts = re.split(r"(\d+)", name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


# images ajoutees aux scans qui ne sont pas des pages du tome : pages de
# credits ou de recrutement des equipes de traduction, conventionnellement
# nommees pour se ranger a la fin (« zzz-credits.jpg »). Mots compares au nom
# du fichier (sans dossier ni extension, en minuscules) : un mot entier, ou un
# debut de nom (« ^zz » : « zz », « zzz »... suivi d'un separateur).
# Reglables dans les preferences (voir set_extra_page_words).
DEFAULT_EXTRA_PAGE_WORDS = ("^zz", "credits", "credit", "recrutement", "recruitment")


def _extra_pattern(word):
    word = word.strip().lower()
    if word.startswith("^"):
        return re.compile("^" + re.escape(word[1:]) + r"\w*?[\W_]")
    return re.compile(r"(?:^|[\W_])" + re.escape(word) + r"(?:[\W_]|$)")


EXTRA_IMAGE_PATTERNS = [_extra_pattern(w) for w in DEFAULT_EXTRA_PAGE_WORDS]


def set_extra_page_words(words):
    """Mots des images a ne pas compter comme des pages (preferences) ; None :
    ceux d'origine. Vaut pour les archives ouvertes ensuite."""
    global EXTRA_IMAGE_PATTERNS
    words = DEFAULT_EXTRA_PAGE_WORDS if words is None else words
    EXTRA_IMAGE_PATTERNS = [_extra_pattern(w) for w in words
                            if isinstance(w, str) and w.strip().lstrip("^")]


def _without_extras(names):
    """Pages sans les images parasites (EXTRA_IMAGE_PATTERNS). Jamais au
    point de vider le tome : sans aucune page restante, tout est garde."""
    kept = [n for n in names
            if not any(p.search(Path(n).stem.lower()) for p in EXTRA_IMAGE_PATTERNS)]
    return kept or names


def _epub_spine_images(ar, images):
    """Images citees par les pages du spine d'un EPUB, dans l'ordre ; [] si
    l'archive n'est pas un EPUB lisible."""
    import posixpath
    from urllib.parse import unquote

    def read_text(name):
        info = ar.getinfo(name)
        if (getattr(info, "file_size", 0) or 0) > MAX_COMICINFO_BYTES:
            return None
        return ar.read(name)

    names = set(ar.namelist())
    if "META-INF/container.xml" not in names:
        return []
    container = safe_xml.fromstring(read_text("META-INF/container.xml"))
    rootfile = next((el.get("full-path") for el in container.iter()
                     if el.tag.endswith("rootfile") and el.get("full-path")), None)
    if not rootfile or rootfile not in names:
        return []
    opf = safe_xml.fromstring(read_text(rootfile))
    base = posixpath.dirname(rootfile)
    manifest = {el.get("id"): el.get("href") for el in opf.iter()
                if el.tag.endswith("item") and el.get("id") and el.get("href")}
    order, seen = [], set()

    def add(href, relative_to):
        target = posixpath.normpath(posixpath.join(relative_to, unquote(href.split("#")[0])))
        if target in images and target not in seen:
            seen.add(target)
            order.append(target)

    for el in opf.iter():
        if not el.tag.endswith("itemref") or el.get("idref") not in manifest:
            continue
        href = manifest[el.get("idref")]
        page = posixpath.normpath(posixpath.join(base, unquote(href.split("#")[0])))
        if page in images:              # image citee directement par le spine
            add(href, base)
            continue
        if page not in names:
            continue
        raw = read_text(page)
        if raw is None:
            continue
        # balises img / image (SVG) d'une page XHTML : lues par motif, une
        # page de BD contenant souvent des entites HTML qu'un parseur XML
        # strict refuse
        for ref in _EPUB_IMAGE_REF.findall(raw.decode("utf-8", "replace")):
            add(ref, posixpath.dirname(page))
    return order


_EPUB_IMAGE_REF = re.compile(r"""(?:src|xlink:href|href)\s*=\s*["']([^"']+)["']""", re.I)
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


def _split_list(text) -> list:
    """« Action, Aventure ; Humour » -> ["Action", "Aventure", "Humour"]."""
    return [p.strip() for p in re.split(r"[,;]", text or "") if p.strip()]


def _isbn_of(text) -> str:
    """ISBN (10 ou 13 caracteres) d'un GTIN ou d'un identifiant
    (« urn:isbn:978-2-505-06352-0 »), ou ""."""
    digits = re.sub(r"[^\dX]", "", re.sub(r"(?i)^\s*(?:urn:)?isbn:?", "", text or "").upper())
    if len(digits) == 13 and digits.startswith(("978", "979")):
        return digits
    return digits if len(digits) == 10 else ""


def _number(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def parse_opf(opf):
    """Metadonnees d'un paquet OPF (element racine deja parse) sous la forme
    de Archive.read_comicinfo (voir Archive._read_opf)."""
    def local(el):
        return el.tag.rsplit("}", 1)[-1]

    def texts(name):
        return [el.text.strip() for el in opf.iter() if local(el) == name
                and el.text and el.text.strip()]

    metas = {}        # <meta name="calibre:series" content="..."> (EPUB 2)
    refines = {}      # <meta refines="#id" property="group-position"> (EPUB 3)
    collections = []  # (id, titre) des <meta property="belongs-to-collection">
    for el in opf.iter():
        if local(el) != "meta":
            continue
        if el.get("name") and el.get("content"):
            metas[el.get("name")] = el.get("content").strip()
        prop, value = el.get("property"), (el.text or "").strip()
        if prop == "belongs-to-collection" and value:
            collections.append((el.get("id"), value))
        elif el.get("refines") and prop and value:
            refines[(el.get("refines").lstrip("#"), prop)] = value
    series = number = None
    if collections:
        coll_id, series = collections[0]
        number = _number(refines.get((coll_id, "group-position")))
    elif metas.get("calibre:series"):
        series = metas["calibre:series"]
        number = _number(metas.get("calibre:series_index"))
    dates = [m.group(1) for d in texts("date") if (m := _YEAR.search(d))]
    creators = texts("creator")
    direction = next((el.get("page-progression-direction") for el in opf.iter()
                      if local(el) == "spine" and el.get("page-progression-direction")), None)
    isbn = next((i for i in map(_isbn_of, texts("identifier")) if i), "")
    description = texts("description")
    titles = texts("title")
    return {
        "series": series,
        "title": titles[0] if titles else None,
        "number": number,
        "year": int(dates[0]) if dates else None,
        "month": None, "day": None,
        "publisher": (texts("publisher") or [None])[0],
        "authors": creators[:1],
        "reading_direction": direction if direction in ("rtl", "ltr") else None,
        "count": None,
        "genres": [g for s in texts("subject") for g in _split_list(s)],
        "summary": description[0] if description else None,
        "language": (texts("language") or [None])[0],
        "gtin": isbn,
        "embedded": "opf",
    }


def _image_rows(image, step):
    """Lignes de pixels (bytes) d'une QImage en niveaux de gris 8 bits, une
    sur `step`."""
    width, per_line = image.width(), image.bytesPerLine()
    bits = image.constBits()
    data = bits.tobytes() if hasattr(bits, "tobytes") else bytes(bits)
    return [data[y * per_line: y * per_line + width] for y in range(0, image.height(), step)]


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
        # tome d'un serveur de lecture : RemoteArchive (meme interface, voir
        # beheread.infra.servers)
        if cls is Archive and isinstance(path, str) and path.startswith("beheread-server:"):
            from beheread.infra import servers
            return servers.registry.open(path)
        # tome virtuel : ses chapitres a la suite (VirtualArchive, meme interface)
        if cls is Archive and isinstance(path, str) and path.startswith("beheread-virtual:"):
            from beheread.infra import virtual
            return virtual.VirtualArchive(path)
        # un PDF est servi par PdfArchive (meme interface) : les appelants
        # continuent d'ecrire simplement Archive(chemin)
        fmt = _detect_format(path) if cls is Archive else None
        if fmt == "pdf" or (fmt == "unknown" and Path(path).suffix.lower() == ".pdf"):
            return super().__new__(PdfArchive)
        obj = super().__new__(cls)
        obj._format = fmt   # reutilise par __init__ : la signature n'est lue qu'une fois
        return obj

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.closed = False
        self._solid_dir = None      # RAR solide : dossier d'extraction (prepare_reading)
        self._solid_ready = False
        self._solid_failed = False
        fmt = getattr(self, "_format", None) or _detect_format(path)
        ext = Path(path).suffix.lower()

        if fmt == "zip" or (fmt == "unknown" and ext in (".cbz", ".zip", ".epub")):
            try:
                self._ar = zipfile.ZipFile(path)
            except zipfile.BadZipFile as e:
                raise ArchiveError(tr("Archive ZIP invalide :") + f"\n{path}\n{e}") from e
        elif fmt == "rar" or (fmt == "unknown" and ext in (".cbr", ".rar")):
            _init_rarfile()
            if _rar_error:
                raise ArchiveError(_rar_error)
            try:
                self._ar = _rarfile.RarFile(path)
            except _rarfile.RarCannotExec as e:
                raise ArchiveError(_no_rar_tool(e)) from e
            except Exception as e:
                raise ArchiveError(tr("Impossible d'ouvrir l'archive RAR :") + f"\n{path}\n{e}") from e
        else:
            raise ArchiveError(tr("Format d'archive non reconnu :") + f"\n{path}")

        names = []
        for n in self._ar.namelist():
            p = Path(n)
            if p.suffix.lower() not in IMAGE_EXTS:
                continue
            if "__MACOSX" in p.parts or p.name.startswith("."):
                continue
            names.append(n)
        names.sort(key=_natural_key)
        names = _without_extras(names)
        if not names:
            self.close()
            raise ArchiveError(tr("Aucune image trouvée dans l'archive :") + f"\n{path}")
        if fmt == "zip" or ext == ".epub":
            names = self._epub_order(names)
        self.pages = names

    def __len__(self):
        return len(self.pages)

    def _epub_order(self, names):
        """EPUB : pages dans l'ordre de lecture declare par le livre (spine
        du fichier OPF : chaque page XHTML et les images qu'elle affiche),
        et non dans l'ordre des noms de fichiers - certains EPUB nomment
        leurs images sans ordre (empreintes, numeros sans zeros). Les images
        que le spine ne cite pas suivent, dans l'ordre des noms. Archive sans
        OPF exploitable : ordre des noms, inchange."""
        try:
            spine = _epub_spine_images(self._ar, set(names))
        except Exception:
            logging.warning("Ordre de lecture EPUB illisible, ordre des noms : %s",
                            self.path, exc_info=True)
            return names
        if not spine:
            return names
        cited = set(spine)
        return spine + [n for n in names if n not in cited]

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
                tr("Entrée anormalement volumineuse ignorée ({size} octets) :\n{name}\n"
                   "dans {path}", size=size, name=name, path=self.path))

    def read_page(self, index: int) -> bytes:
        name = self.pages[index]
        self._guard_size(name, MAX_PAGE_BYTES)
        extracted = self._extracted_file(name)
        if extracted is not None:
            try:
                return extracted.read_bytes()
            except OSError:
                logging.warning("Page extraite illisible, lecture dans l'archive : %s",
                                extracted, exc_info=True)
        with self._lock:
            if self.closed:
                # lecteur ferme pendant un prechargement : cas normal, pas une erreur
                raise ArchiveClosedError(self.path)
            return self._ar.read(name)

    # ------------------------------------------------------------ RAR solide
    def prepare_reading(self):
        """Ouverture dans le lecteur : un RAR solide est extrait en une passe,
        en arriere-plan (voir SOLID_PREFIX). En attendant, les pages sont
        lues dans l'archive comme avant ; les premieres, au debut du flux,
        restent rapides. Sans effet sur les autres formats et pour les
        vignettes, qui ne lisent que la premiere page."""
        if self._solid_dir is not None or not self._is_solid_rar():
            return
        total = 0
        for name in self.pages:
            try:
                total += getattr(self._ar.getinfo(name), "file_size", 0) or 0
            except Exception:
                return
        if total > SOLID_MAX_BYTES or not _rar_tools:
            return
        self._solid_dir = Path(tempfile.mkdtemp(prefix=SOLID_PREFIX))
        threading.Thread(target=self._extract_all, name="beheread-rar-solide",
                         daemon=True).start()

    def _is_solid_rar(self) -> bool:
        if _rarfile is None or not isinstance(self._ar, _rarfile.RarFile):
            return False
        try:
            return bool(self._ar.is_solid())
        except Exception:
            return False

    def _extract_all(self):
        dest = self._solid_dir
        _purge_stale_extractions(keep=dest)
        try:
            subprocess.run(_solid_command(self.path, str(dest)), stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=SOLID_TIMEOUT, check=True, creationflags=_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            logging.warning("Extraction du RAR solide impossible, lecture page par page : %s",
                            self.path, exc_info=True)
            with self._lock:
                self._solid_failed = True
            shutil.rmtree(dest, ignore_errors=True)
            return
        with self._lock:
            if self.closed:   # lecteur ferme pendant l'extraction
                shutil.rmtree(dest, ignore_errors=True)
                return
            self._solid_ready = True

    def _extracted_file(self, name):
        """Fichier extrait de la page `name`, ou None (pas encore pret, pas
        un RAR solide, ou chemin suspect)."""
        with self._lock:
            if not self._solid_ready or self._solid_failed or self.closed:
                return None
            root = self._solid_dir
        path = (root / name).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            return None   # chemin hors du dossier d'extraction, ou absent
        return path

    def read_first_page(self) -> bytes:
        return self.read_page(0)

    def read_image(self, index: int, max_height: int = 0):
        """Page decodee (QImage, nulle si illisible). Avec `max_height`, une
        image plus haute est decodee directement reduite (vignette, apercu) :
        le decodeur JPEG saute alors les details inutiles, bien plus vite
        qu'un decodage complet suivi d'une reduction."""
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
        from PySide6.QtGui import QImage, QImageReader
        data = QByteArray(self.read_page(index))
        if not max_height:
            return QImage.fromData(data)
        buf = QBuffer(data)
        buf.open(QIODevice.ReadOnly)
        reader = QImageReader(buf)
        size = reader.size()
        if size.isValid() and size.height() > max_height:
            reader.setScaledSize(size.scaled(QSize(size.width(), max_height),
                                             Qt.KeepAspectRatio))
        return reader.read()

    def read_comicinfo(self):
        """Lit et parse ComicInfo.xml (standard ComicRack) a la racine de
        l'archive, s'il existe - a defaut, pour un EPUB, ses metadonnees OPF
        (voir _read_opf). Renvoie un dict ou None si absent/illisible.
        C'est la source de metadonnees prioritaire : locale, fiable, et
        100% hors ligne si l'utilisateur a tague ses fichiers."""
        try:
            names = self._ar.namelist()
        except Exception:
            logging.warning("Liste des fichiers illisible dans %s", self.path, exc_info=True)
            return None
        target = next((n for n in names if Path(n).name.lower() == "comicinfo.xml"), None)
        if target is None:
            return self._read_opf(names)
        try:
            self._guard_size(target, MAX_COMICINFO_BYTES)
            with self._lock:
                raw = self._ar.read(target)
            root = safe_xml.fromstring(raw)
        except safe_xml.UnsafeXmlError:
            # DOCTYPE present : refus par principe (anti expansion d'entites
            # / XXE). Un ComicInfo.xml legitime n'en contient jamais.
            logging.warning("ComicInfo.xml avec DOCTYPE ignore (securite) dans %s",
                            self.path)
            return None
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
            # nombre de tomes de la serie (le plus grand vaut pour la serie,
            # comme dans Komga), genres, resume, langue, ISBN
            "count": integer("Count") or None,
            "genres": _split_list(text("Genre")),
            "summary": text("Summary"),
            "language": text("LanguageISO"),
            "gtin": _isbn_of(text("GTIN")),
            "embedded": "comicinfo",
        }

    def _read_opf(self, names):
        """Metadonnees OPF d'un EPUB, sous la forme de read_comicinfo, ou None.
        Serie et numero : belongs-to-collection / group-position (EPUB 3),
        sinon calibre:series / calibre:series_index ; sens de lecture :
        page-progression-direction du spine (comme Komga)."""
        if "META-INF/container.xml" not in names:
            return None
        try:
            def read(name):
                self._guard_size(name, MAX_COMICINFO_BYTES)
                with self._lock:
                    return self._ar.read(name)
            container = safe_xml.fromstring(read("META-INF/container.xml"))
            rootfile = next((el.get("full-path") for el in container.iter()
                             if el.tag.endswith("rootfile") and el.get("full-path")), None)
            if not rootfile or rootfile not in names:
                return None
            opf = safe_xml.fromstring(read(rootfile))
        except safe_xml.UnsafeXmlError:
            logging.warning("Metadonnees EPUB avec DOCTYPE ignorees (securite) dans %s", self.path)
            return None
        except Exception:
            logging.warning("Metadonnees EPUB illisibles dans %s", self.path, exc_info=True)
            return None
        return parse_opf(opf)

    def find_isbn(self):
        """ISBN lu en code-barres sur la quatrieme de couverture (dernieres
        pages) ou, a defaut, sur les premieres pages ; None si aucun (voir
        core/barcode.py). Lit au plus ISBN_SCAN_PAGES pages, decodees
        reduites ; rien pour un RAR solide, ou la derniere page ne se lit
        qu'apres decompression de tout le tome."""
        if self._is_solid_rar() or not self.pages:
            return None
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QTransform

        from beheread.core import barcode
        count = len(self.pages)
        order = [i for i in (count - 1, count - 2, 0, 1) if 0 <= i < count]
        for index in list(dict.fromkeys(order))[:ISBN_SCAN_PAGES]:
            try:
                image = self.read_image(index, ISBN_SCAN_HEIGHT)
            except Exception:
                logging.debug("Page illisible pour l'ISBN : %s [%d]", self.path, index,
                              exc_info=True)
                continue
            if image.isNull():
                continue
            gray = image.convertToFormat(QImage.Format_Grayscale8)
            # code horizontal, puis vertical (dos de certains albums) ; a
            # defaut, lignes etirees par interpolation : le seuil situe alors
            # les bords des barres a mieux qu'un pixel pres (barres fines)
            turned = gray.transformed(QTransform().rotate(90))
            for img in (gray, turned):
                isbn = barcode.decode(_image_rows(img, barcode.ROW_STEP))
                if isbn:
                    return isbn
            for img in (gray, turned):
                wide = img.scaled(img.width() * 2, img.height(), Qt.IgnoreAspectRatio,
                                  Qt.SmoothTransformation)
                isbn = barcode.decode(_image_rows(wide, barcode.ROW_STEP))
                if isbn:
                    return isbn
        return None

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
            # extraction terminee (ou echouee) : dossier supprime ici ; en
            # cours, le thread d'extraction le supprimera a sa fin
            if self._solid_dir is not None and (self._solid_ready or self._solid_failed):
                shutil.rmtree(self._solid_dir, ignore_errors=True)


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _solid_command(archive_path, dest):
    """Commande d'extraction complete avec l'outil RAR retenu (chemin absolu,
    voir _init_rarfile), ou None. Mot de passe factice : une archive chiffree
    echoue au lieu d'attendre une saisie (elle est alors lue page par page,
    avec le message d'erreur habituel)."""
    if "unrar" in _rar_tools:
        return [_rar_tools["unrar"], "x", "-y", "-inul", "-p-", "-o+", archive_path,
                dest + os.sep]
    if "sevenzip" in _rar_tools:
        return [_rar_tools["sevenzip"], "x", "-y", "-bd", "-pbeheread", f"-o{dest}",
                archive_path]
    if "bsdtar" in _rar_tools:
        return [_rar_tools["bsdtar"], "-x", "-f", archive_path, "-C", dest]
    return None


def _purge_stale_extractions(keep=None):
    """Supprime les dossiers d'extraction laisses par un arret brutal."""
    now = time.time()
    try:
        candidates = list(Path(tempfile.gettempdir()).glob(SOLID_PREFIX + "*"))
    except OSError:
        return
    for d in candidates:
        try:
            if d != keep and d.is_dir() and now - d.stat().st_mtime > SOLID_STALE_AGE:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            continue


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
        except ImportError as e:
            raise ArchiveError(tr("La lecture des PDF nécessite le module QtPdf "
                                  "(PySide6-Addons), introuvable.")) from e
        self._doc = QPdfDocument()
        err = self._doc.load(path)
        if err != QPdfDocument.Error.None_:
            name = getattr(err, "name", str(err))
            self._doc.close()
            if name == "IncorrectPassword":
                raise ArchiveError(tr("PDF protégé par un mot de passe :") + f"\n{path}")
            raise ArchiveError(tr("PDF illisible ({name}) :", name=name) + f"\n{path}")
        count = self._doc.pageCount()
        if count <= 0:
            self._doc.close()
            raise ArchiveError(tr("Aucune page dans le PDF :") + f"\n{path}")
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

    def _is_solid_rar(self) -> bool:
        return False

    def prepare_reading(self):
        pass   # pages rendues a la demande

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
    """Tome suivant de la meme serie dans le dossier de `path`, ou None. Les
    sous-dossiers ne sont pas parcourus : un tome ouvert depuis un dossier de
    telechargements ou la racine d'un disque ne declenche pas le parcours de
    toute l'arborescence."""
    from beheread.core.series import next_volume
    if path.startswith(("beheread-server:", "beheread-virtual:")):
        return None   # tome d'un serveur ou virtuel : voir LibraryWidget.next_volume
    try:
        siblings = [str(p) for p in Path(path).parent.iterdir()
                    if p.suffix.lower() in SUPPORTED_EXTS and p.is_file()]
    except OSError:
        return None
    return next_volume(path, siblings)


def scan_tree(folder: str):
    """Parcourt un dossier et ses sous-dossiers en une seule passe.

    Renvoie ([(chemin, stat)] des fichiers CBZ/CBR/EPUB/PDF en tri naturel,
    [dossiers parcourus], dossier lui-meme compris). Le stat vient de la
    liste du dossier (gratuit sous Windows, ou FindNextFile le fournit) : ni
    l'identification des tomes ni la detection des fichiers cloud n'ont a
    refaire un appel systeme par fichier, et les dossiers servent tels quels
    a la surveillance. Comme Path.rglob, les jonctions Windows sont suivies,
    pas les liens symboliques de dossier. Un sous-dossier illisible est
    ignore sans faire echouer le reste."""
    root = str(Path(folder))
    if not os.path.isdir(root):
        return [], []
    files, dirs, stack = [], [], [root]
    while stack:
        d = stack.pop()
        dirs.append(d)
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            logging.warning("Dossier illisible : %s", d, exc_info=True)
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif (os.path.splitext(entry.name)[1].lower() in SUPPORTED_EXTS
                      and entry.is_file()):
                    files.append((entry.path, entry.stat()))
            except OSError:
                continue
    # tri naturel des seules archives retenues (pas des images, ComicInfo.xml
    # et sous-dossiers traverses)
    files.sort(key=lambda f: _natural_key(f[0]))
    return files, dirs


def scan_folder(folder: str):
    """Liste recursivement les fichiers CBZ/CBR/EPUB/PDF d'un dossier."""
    return [path for path, _st in scan_tree(folder)[0]]
