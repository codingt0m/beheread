"""Serveurs de lecture : Komga, Kavita et tout serveur OPDS.

Les tomes d'un serveur sont lus en continu, page par page, sans copie sur le
disque. Ils circulent dans l'application comme des tomes locaux, sous un
chemin de la forme « beheread-server:<serveur>:<tome> » : Archive(chemin)
renvoie alors une RemoteArchive (meme interface), et la progression, les
statistiques et les vignettes sont rangees sous ce chemin (Store.key_for
n'y trouve aucun fichier et le garde tel quel).

* Komga : API REST (liste des tomes, pages, vignettes, progression) ;
  identifiant + mot de passe, ou cle d'API seule.
* Kavita : flux OPDS de la cle d'API (liste et pages, avec l'extension de
  lecture en continu OPDS-PSE), API REST pour envoyer la progression.
* OPDS : tout autre serveur. Pages en continu si le serveur connait
  OPDS-PSE ; sinon le fichier CBZ est charge en memoire a l'ouverture.

Securite : les identifiants ne partent que vers l'adresse du serveur (une
redirection ou un lien vers une autre adresse est refuse), les reponses sont
bornees en taille, et les flux XML passent par safe_xml. Aucune adresse n'est
ecrite dans le journal (celle de Kavita contient la cle d'API).
"""

import base64
import hashlib
import io
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from beheread.i18n import N_, tr
from beheread.infra import net, safe_xml
from beheread.infra.archive import (
    IMAGE_EXTS,
    MAX_PAGE_BYTES,
    Archive,
    ArchiveClosedError,
    ArchiveError,
    _natural_key,
    _without_extras,
)

PREFIX = "beheread-server:"
KINDS = ("beheread", "komga", "kavita", "opds")
KIND_LABELS = {"beheread": N_("Serveur Beheread"), "komga": "Komga", "kavita": "Kavita",
               "opds": N_("OPDS (autre serveur)")}
# tome d'un serveur Beheread : identifie par son empreinte de contenu
# (« c1-<hex> » dans le chemin, « c1:<hex> » partout ailleurs, voir
# LibraryStore.key_for) : progression et statistiques communes avec une copie
# locale du meme fichier
FP_BOOK = "c1-"

TIMEOUT = 20
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_FEED_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 600 * 1024 * 1024    # tome OPDS sans lecture en continu, en memoire
MAX_BOOKS = 20000
MAX_FEEDS = 2000                      # pages de flux OPDS parcourues au plus
KOMGA_PAGE_SIZE = 500
COVER_MAX_HEIGHT = 600                # au-dela, la vignette du serveur est trop petite

Number = Union[int, float]

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

NS = {"atom": "http://www.w3.org/2005/Atom",
      "pse": "http://vaemendis.net/opds-pse/ns",
      "dc": "http://purl.org/dc/terms/"}
REL_STREAM = "http://vaemendis.net/opds-pse/stream"
REL_ACQUISITION = "http://opds-spec.org/acquisition"
REL_THUMBNAILS = ("http://opds-spec.org/image/thumbnail", "http://opds-spec.org/thumbnail")
REL_IMAGES = ("http://opds-spec.org/image", "http://opds-spec.org/cover")
# liens de navigation a ne pas suivre : recherche, facettes, retour en arriere
REL_SKIPPED = ("self", "start", "up", "search", "related", "previous", "prev", "first", "last",
               "http://opds-spec.org/facet", "http://opds-spec.org/shelf",
               "http://opds-spec.org/subscriptions", "http://opds-spec.org/crawlable")
ZIP_TYPES = ("application/zip", "application/x-cbz", "application/vnd.comicbook+zip",
             "application/x-zip-compressed")


class ServerError(Exception):
    """Serveur injoignable, identifiants refuses, reponse inattendue.
    `status` : code HTTP de la reponse, s'il y en a une."""

    def __init__(self, message="", status=None):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- chemins

def is_remote(path) -> bool:
    return isinstance(path, str) and path.startswith(PREFIX)


def safe_id(raw) -> str:
    """Identifiant utilisable dans un chemin (lettres, chiffres, - et _) :
    tel quel s'il l'est deja, sinon son empreinte."""
    text = str(raw)
    if _SAFE_ID.match(text):
        return text
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:24]


def make_path(server_id, book_id) -> str:
    return f"{PREFIX}{safe_id(server_id)}:{safe_id(book_id)}"


def split_path(path):
    """(serveur, tome) d'un chemin distant, ou (None, None)."""
    if not is_remote(path):
        return None, None
    server_id, _, book_id = path[len(PREFIX):].partition(":")
    return server_id, book_id


def display_name(path) -> str:
    """Titre d'un tome : celui donne par son serveur pour un tome distant,
    le nom du fichier sans extension sinon."""
    if is_remote(path):
        book = registry.book(path)
        return book.title if book is not None else split_path(path)[1]
    return Path(path).stem


# ---------------------------------------------------------------- modeles

@dataclass
class ServerConfig:
    id: str
    kind: str          # "komga", "kavita" ou "opds"
    name: str
    url: str
    user: str = ""

    @classmethod
    def from_dict(cls, data) -> Optional["ServerConfig"]:
        if not isinstance(data, dict):
            return None
        sid, kind, url = data.get("id"), data.get("kind"), data.get("url")
        if not isinstance(sid, str) or not _SAFE_ID.match(sid) or kind not in KINDS:
            return None
        if not isinstance(url, str) or not url.strip():
            return None
        return cls(id=sid, kind=kind, name=str(data.get("name") or url), url=url.strip(),
                   user=str(data.get("user") or ""))

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "name": self.name, "url": self.url,
                "user": self.user}


@dataclass
class RemoteBook:
    server_id: str
    book_id: str
    title: str
    series: str
    number: Optional[Number] = None
    pages: int = 0
    # progression connue du serveur : (index de la page, termine), ou None
    progress: Optional[tuple] = None
    author: str = ""
    year: Optional[int] = None
    progress_ts: float = 0.0   # heure de cette progression (serveur Beheread), 0 si inconnue
    stream: str = ""      # gabarit d'adresse des pages (OPDS-PSE) : {pageNumber}
    download: str = ""    # adresse du fichier complet (OPDS sans PSE)
    cover: str = ""       # adresse de la vignette
    ids: dict = field(default_factory=dict)   # Kavita : bibliotheque, serie, volume, chapitre

    @property
    def path(self) -> str:
        return make_path(self.server_id, self.book_id)


# ---------------------------------------------------------------- HTTP

def _origin(url) -> tuple:
    parts = urllib.parse.urlsplit(url)
    port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    return parts.scheme.lower(), (parts.hostname or "").lower(), port


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Les identifiants ne doivent jamais suivre une redirection vers une
    autre adresse que celle du serveur."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(newurl) != _origin(req.full_url):
            raise ServerError(tr("Le serveur redirige vers une autre adresse : refusé."))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def normalize_url(url) -> str:
    """Adresse du serveur, avec http:// si aucun protocole n'est donne et sans
    / final. Leve ServerError si elle n'est pas exploitable."""
    url = (url or "").strip()
    if url and "://" not in url:
        url = "http://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ServerError(tr("Adresse non reconnue : par exemple http://192.168.1.20:25600"))
    return url.rstrip("/")


class _Http:
    """Requetes vers un seul serveur (memes en-tetes, meme origine)."""

    def __init__(self, base, headers=None):
        self.base = normalize_url(base)
        self.origin = _origin(self.base)
        self.headers = {"User-Agent": net.APP_USER_AGENT, **(headers or {})}
        self._opener = urllib.request.build_opener(_SameOriginRedirect())

    def url(self, path) -> str:
        """Adresse absolue d'un chemin ou d'un lien du serveur ; leve
        ServerError pour une autre adresse."""
        url = urllib.parse.urljoin(self.base + "/", path)
        if _origin(url) != self.origin:
            raise ServerError(tr("Lien vers une autre adresse ignoré."))
        return url

    def request(self, path, method="GET", body=None, limit=MAX_JSON_BYTES, accept="*/*",
                headers=None) -> bytes:
        data = None
        all_headers = {**self.headers, "Accept": accept, **(headers or {})}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            all_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url(path), data=data, method=method,
                                     headers=all_headers)
        try:
            with self._opener.open(req, timeout=TIMEOUT) as resp:
                content = resp.read(limit + 1)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise ServerError(tr("Identifiants refusés par le serveur."), e.code) from e
            if e.code == 404:
                raise ServerError(tr("Adresse introuvable sur le serveur (erreur 404) : "
                                     "vérifiez le type de serveur et l'adresse."), e.code) from e
            raise ServerError(tr("Le serveur a répondu par une erreur ({code}).",
                                 code=e.code), e.code) from e
        except ServerError:
            raise
        except (urllib.error.URLError, OSError, ValueError) as e:
            reason = getattr(e, "reason", None) or e
            raise ServerError(tr("Serveur injoignable : {reason}", reason=reason)) from e
        if len(content) > limit:
            raise ServerError(tr("Réponse du serveur anormalement volumineuse."))
        return content

    def json(self, path, method="GET", body=None):
        content = self.request(path, method, body, accept="application/json")
        if not content:
            return None
        try:
            return json.loads(content.decode("utf-8"))
        except ValueError as e:
            raise ServerError(tr("Réponse inattendue du serveur : est-ce bien un serveur "
                                 "de ce type ?")) from e

    def image(self, url) -> bytes:
        data = self.request(url, limit=MAX_PAGE_BYTES, accept="image/*")
        if not data:
            raise ServerError(tr("Page vide reçue du serveur."))
        return data


def _basic(user, secret) -> dict:
    token = base64.b64encode(f"{user}:{secret}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


# ---------------------------------------------------------------- clients

class Client:
    """Interface commune des clients de serveur."""

    supports_progress = False

    def __init__(self, config: ServerConfig, secret: str):
        self.config = config
        self.secret = secret or ""

    def check(self) -> dict:
        """{"version": texte, "count": nombre de tomes ou None}. Leve ServerError."""
        raise NotImplementedError

    def books(self) -> list:
        """Tous les tomes du serveur (RemoteBook). Leve ServerError."""
        raise NotImplementedError

    def page(self, book, index) -> bytes:
        raise NotImplementedError

    def cover(self, book) -> Optional[bytes]:
        """Vignette du serveur, ou None s'il n'en fournit pas."""
        return None

    def file(self, book) -> bytes:
        raise ServerError(tr("Ce tome ne peut pas être lu en continu."))

    def push_progress(self, book, index, finished):
        """Envoie la progression (index de la page en cours, tome termine)."""


def _year(text) -> Optional[int]:
    match = re.match(r"^(\d{4})", str(text or ""))
    return int(match.group(1)) if match else None


def _number(value) -> Optional[Number]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) > 1e6:   # NaN, valeurs aberrantes
        return None
    return int(number) if number.is_integer() else number


class KomgaClient(Client):
    supports_progress = True

    def __init__(self, config, secret):
        super().__init__(config, secret)
        auth = _basic(config.user, self.secret) if config.user else {"X-API-Key": self.secret}
        self.http = _Http(config.url, auth)

    def check(self):
        self.http.json("/api/v1/users/me")
        version = "Komga"
        try:
            info = self.http.json("/api/v1/actuator/info") or {}
            number = ((info.get("build") or {}).get("version") or "").strip()
            if re.match(r"^[\w.\-]{1,32}$", number):
                version = f"Komga {number}"
        except ServerError:
            pass   # reserve aux administrateurs sur certaines versions
        page = self.http.json("/api/v1/books?size=1") or {}
        count = page.get("totalElements")
        return {"version": version, "count": count if isinstance(count, int) else None}

    def books(self):
        books, page = [], 0
        while len(books) < MAX_BOOKS:
            data = self.http.json(f"/api/v1/books?page={page}&size={KOMGA_PAGE_SIZE}"
                                  "&sort=metadata.numberSort,asc")
            if not isinstance(data, dict) or not isinstance(data.get("content"), list):
                raise ServerError(tr("Réponse inattendue du serveur : est-ce bien un serveur "
                                     "de ce type ?"))
            for item in data["content"]:
                book = self._book(item)
                if book is not None:
                    books.append(book)
            if data.get("last", True) or not data["content"]:
                break
            page += 1
        return books

    def _book(self, item):
        if not isinstance(item, dict) or not item.get("id"):
            return None
        media = item.get("media") or {}
        pages = media.get("pagesCount")
        if not isinstance(pages, int) or pages <= 0:
            return None   # analyse en cours, format non pris en charge
        meta = item.get("metadata") or {}
        authors = [a.get("name") for a in meta.get("authors") or []
                   if isinstance(a, dict) and isinstance(a.get("name"), str)]
        writers = [a.get("name") for a in meta.get("authors") or []
                   if isinstance(a, dict) and a.get("role") == "writer" and a.get("name")]
        progress = None
        rp = item.get("readProgress")
        if isinstance(rp, dict):
            page = rp.get("page") if isinstance(rp.get("page"), int) else 1
            progress = (min(max(0, page - 1), pages - 1), bool(rp.get("completed")))
        title = str(meta.get("title") or item.get("name") or item["id"])
        return RemoteBook(
            server_id=self.config.id, book_id=safe_id(item["id"]), title=title,
            series=str(item.get("seriesTitle") or title),
            number=_number(meta.get("numberSort", item.get("number"))), pages=pages,
            progress=progress, author=", ".join(dict.fromkeys(writers or authors)),
            year=_year(meta.get("releaseDate")), ids={"komga": str(item["id"])})

    def page(self, book, index):
        return self.http.image(f"/api/v1/books/{_q(book.ids['komga'])}/pages/{index + 1}")

    def cover(self, book):
        return self.http.image(f"/api/v1/books/{_q(book.ids['komga'])}/thumbnail")

    def push_progress(self, book, index, finished):
        self.http.request(f"/api/v1/books/{_q(book.ids['komga'])}/read-progress",
                          method="PATCH", body={"page": index + 1, "completed": bool(finished)})


def _q(text) -> str:
    return urllib.parse.quote(str(text), safe="")


class OpdsClient(Client):
    """Serveur OPDS 1.x, avec ou sans lecture en continu (OPDS-PSE)."""

    def __init__(self, config, secret):
        super().__init__(config, secret)
        auth = _basic(config.user, self.secret) if config.user and self.secret else {}
        self.http = _Http(config.url, auth)
        self.root = self.http.base

    # ----- flux
    def _feed(self, url):
        content = self.http.request(url, limit=MAX_FEED_BYTES,
                                    accept="application/atom+xml, application/xml")
        try:
            root = safe_xml.fromstring(content)
        except Exception as e:
            raise ServerError(tr("Réponse inattendue du serveur : est-ce bien un flux OPDS ?")) from e
        if root.tag != f"{{{NS['atom']}}}feed":
            raise ServerError(tr("Réponse inattendue du serveur : est-ce bien un flux OPDS ?"))
        return root

    def check(self):
        feed = self._feed(self.root)
        title = (feed.findtext("atom:title", "", NS) or "").strip()
        return {"version": title[:60] or "OPDS", "count": None}

    def books(self):
        """Parcours du catalogue (navigation et pages suivantes), borne. Un
        tome vu dans plusieurs flux (« nouveautes », « series »...) prend
        le nom de serie du flux le plus petit ou il apparait : le plus
        specifique, en general celui de sa serie."""
        seen_feeds, queue = set(), [self.root]
        found = OrderedDict()    # identifiant -> (RemoteBook, taille du flux)
        while queue and len(seen_feeds) < MAX_FEEDS and len(found) < MAX_BOOKS:
            url = queue.pop(0)
            if url in seen_feeds:
                continue
            seen_feeds.add(url)
            try:
                feed = self._feed(url)
            except ServerError:
                if url == self.root:
                    raise
                logging.warning("Flux OPDS illisible, ignore")
                continue
            feed_title = (feed.findtext("atom:title", "", NS) or "").strip()
            entries = feed.findall("atom:entry", NS)
            books = []
            for entry in entries:
                book, links = self._entry(entry, feed_title)
                if book is not None:
                    books.append(book)
                for link in links:
                    if link not in seen_feeds:
                        queue.append(link)
            for link in feed.findall("atom:link", NS):
                if link.get("rel") == "next" and link.get("href"):
                    try:
                        queue.insert(0, self.http.url(link.get("href")))
                    except ServerError:
                        pass
            for book in books:
                known = found.get(book.book_id)
                if known is None or len(entries) < known[1]:
                    found[book.book_id] = (book, len(entries))
        return [book for book, _size in found.values()][:MAX_BOOKS]

    def _entry(self, entry, feed_title):
        """(RemoteBook ou None, liens de navigation a suivre) d'une entree."""
        follow, stream, download, cover, image = [], None, None, "", ""
        for link in entry.findall("atom:link", NS):
            rel, href, kind = link.get("rel") or "", link.get("href") or "", link.get("type") or ""
            if not href:
                continue
            try:
                url = self.http.url(href)
            except ServerError:
                continue
            if rel == REL_STREAM:
                stream = (url, link)
            elif rel.startswith(REL_ACQUISITION):
                if any(t in kind for t in ZIP_TYPES) and download is None:
                    download = url
            elif rel in REL_THUMBNAILS:
                cover = url
            elif rel in REL_IMAGES:
                image = url
            elif "atom+xml" in kind and rel not in REL_SKIPPED:
                follow.append(url)
        if stream is None and download is None:
            return None, follow
        title = (entry.findtext("atom:title", "", NS) or "").strip() or feed_title
        raw_id = (entry.findtext("atom:id", "", NS) or "").strip() or (stream or (download,))[0]
        pages, progress = 0, None
        if stream is not None:
            url, link = stream
            pages = _int(link.get(f"{{{NS['pse']}}}count"))
            last = _int(link.get(f"{{{NS['pse']}}}lastRead"))
            if pages and last:
                progress = (min(max(0, last - 1), pages - 1), last >= pages)
        series, number = _series_and_number(title, feed_title)
        author = ", ".join(n.strip() for n in (a.findtext("atom:name", "", NS)
                                                for a in entry.findall("atom:author", NS)) if n.strip())
        issued = entry.findtext("dc:issued", "", NS) or entry.findtext("atom:published", "", NS)
        book = RemoteBook(
            server_id=self.config.id, book_id=safe_id(raw_id), title=title, series=series,
            number=number, pages=pages, progress=progress, author=author, year=_year(issued),
            stream=stream[0] if stream else "", download=download or "", cover=cover or image,
            ids=_kavita_ids(stream[0]) if stream else {})
        return book, follow

    # ----- lecture
    def page(self, book, index):
        if not book.stream:
            raise ServerError(tr("Ce tome ne peut pas être lu en continu."))
        url = book.stream.replace("{pageNumber}", str(index)).replace("{maxWidth}", "4000")
        return self.http.image(url)

    def cover(self, book):
        return self.http.image(book.cover) if book.cover else None

    def file(self, book):
        if not book.download:
            raise ServerError(tr("Ce tome ne peut pas être lu en continu."))
        return self.http.request(book.download, limit=MAX_FILE_BYTES)


def _int(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _series_and_number(title, feed_title):
    """Serie et numero d'un tome OPDS : deduits de son titre comme d'un nom
    de fichier (« Berserk - Tome 3 »), sinon serie du flux qui le liste."""
    from beheread.core.series import parse_series_ex
    from beheread.core.text import GENERIC_NAMES, strip_accents
    name, number, _kind = parse_series_ex(title, "")
    generic = strip_accents(name).lower() in GENERIC_NAMES if name else True
    if number is not None and not generic:
        return name, number
    return (feed_title or title), number


def _kavita_ids(stream_url) -> dict:
    """Identifiants Kavita lus dans l'adresse de lecture en continu."""
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(stream_url).query)
    ids = {}
    for key in ("libraryId", "seriesId", "volumeId", "chapterId"):
        value = (query.get(key) or [""])[0]
        if value.isdigit():
            ids[key] = int(value)
    return ids


class KavitaClient(OpdsClient):
    """Kavita : flux OPDS de la cle d'API pour la liste et les pages ; API
    REST (jeton obtenu par la cle) pour envoyer la progression."""

    supports_progress = True

    def __init__(self, config, secret):
        Client.__init__(self, config, secret)
        base = normalize_url(config.url)
        match = re.search(r"/api/opds/([^/?#]+)", base)
        if match:   # adresse OPDS complete collee depuis Kavita
            self.secret = self.secret or urllib.parse.unquote(match.group(1))
            base = base[:match.start()]
        self.http = _Http(base)
        self.root = self.http.url(f"/api/opds/{_q(self.secret)}")
        self._token = None
        self._token_lock = threading.Lock()

    def check(self):
        if not self.secret:
            raise ServerError(tr("Kavita demande sa clé d'API (Paramètres > Clé d'API, "
                                 "dans Kavita)."))
        result = super().check()
        self._authenticate()
        return {"version": "Kavita", "count": result["count"]}

    def _authenticate(self) -> str:
        with self._token_lock:
            if self._token:
                return self._token
            data = self.http.json(f"/api/Plugin/authenticate?apiKey={_q(self.secret)}"
                                  "&pluginName=Beheread", method="POST") or {}
            token = data.get("token") if isinstance(data, dict) else None
            if not isinstance(token, str) or not token:
                raise ServerError(tr("Identifiants refusés par le serveur."))
            self._token = token
            return token

    def push_progress(self, book, index, finished):
        ids = book.ids
        if not all(k in ids for k in ("libraryId", "seriesId", "volumeId", "chapterId")):
            return
        body = {**ids, "pageNum": book.pages if finished else index}
        for attempt in (0, 1):
            token = self._authenticate()
            try:
                self.http.request("/api/Reader/progress", method="POST", body=body,
                                  headers={"Authorization": f"Bearer {token}"})
                return
            except ServerError:
                with self._token_lock:
                    self._token = None   # jeton expire : un nouveau, une fois
                if attempt:
                    raise


class BeheReadClient(Client):
    """Serveur Beheread : catalogue, pages et progression d'un profil. Le
    secret est le jeton de cet appareil, obtenu par enroll() (lien
    d'invitation ou code « Ajouter un appareil »)."""

    supports_progress = True
    streams = True          # pages toujours en continu (nombre lu au besoin)
    PAGE_WIDTH = 2752       # plus grand palier : le serveur n'agrandit jamais

    def __init__(self, config, secret):
        super().__init__(config, secret)
        self.http = _Http(config.url, {"Authorization": f"Bearer {self.secret}"})

    def check(self):
        version = self.http.json("/api/v1/version") or {}
        require_version(version.get("desktop_min"))
        me = self.http.json("/api/v1/me") or {}
        library = self.http.json("/api/v1/library") or {}
        name = (me.get("profile") or {}).get("name") or ""
        return {"version": tr("Serveur Beheread, profil {name}", name=name) if name else "Serveur Beheread",
                "count": len(library.get("volumes") or [])}

    def books(self):
        require_version((self.http.json("/api/v1/version") or {}).get("desktop_min"))
        library = self.http.json("/api/v1/library")
        profile = self.http.json("/api/v1/profile") or {}
        if not isinstance(library, dict) or not isinstance(library.get("volumes"), list):
            raise ServerError(tr("Réponse inattendue du serveur : est-ce bien un serveur "
                                 "de ce type ?"))
        series = {s.get("key"): s for s in library.get("series") or [] if isinstance(s, dict)}
        progress = profile.get("progress") if isinstance(profile.get("progress"), dict) else {}
        books = []
        for v in library["volumes"][:MAX_BOOKS]:
            fp = v.get("fp") if isinstance(v, dict) else None
            if not isinstance(fp, str) or not re.match(r"^c1:[0-9a-f]{40}$", fp):
                continue
            s = series.get(v.get("series_key")) or {}
            p = progress.get(fp)
            pages = v.get("pages") if isinstance(v.get("pages"), int) else 0
            state = None
            if isinstance(p, dict) and isinstance(p.get("page"), int):
                state = (p["page"], bool(p.get("finished")))
            books.append(RemoteBook(
                server_id=self.config.id, book_id=FP_BOOK + fp[3:],
                title=str(v.get("title") or fp), series=str(s.get("name") or v.get("title") or ""),
                number=_number(v.get("number")), pages=pages, progress=state,
                progress_ts=float(p.get("ts") or 0) if isinstance(p, dict) else 0.0,
                author=str(s.get("author") or ""),
                year=s.get("year") if isinstance(s.get("year"), int) else None,
                ids={"fp": fp}))
        return books

    def page_count(self, book) -> int:
        manifest = self.http.json(f"/api/v1/volumes/{_q(book.ids['fp'])}/manifest") or {}
        return len(manifest.get("pages") or [])

    def page(self, book, index):
        return self.http.image(f"/api/v1/volumes/{_q(book.ids['fp'])}/pages/{index}"
                               f"?w={self.PAGE_WIDTH}&v=2")

    def cover(self, book):
        return self.http.image(f"/api/v1/covers/{_q(book.ids['fp'])}")

    def push_progress(self, book, index, finished):
        from beheread.core.profile_sync import new_event_id
        now = time.time()
        # l'appareil est celui du jeton : le serveur ignore ce champ
        event = {"id": new_event_id(now), "type": "progress", "device": "desktop", "ts": now,
                 "fp": book.ids["fp"], "page": int(index), "total": int(book.pages),
                 "finished": bool(finished)}
        self.http.json("/api/v1/events", method="POST", body={"events": [event]})


def _version_tuple(text):
    return tuple(int(n) for n in re.findall(r"\d+", str(text or ""))[:3]) or (0,)


def require_version(minimum):
    """Leve ServerError si le serveur Beheread exige une version plus recente
    de l'application (« tout le monde a jour »)."""
    from beheread.version import __version__
    if minimum and _version_tuple(__version__) < _version_tuple(minimum):
        raise ServerError(tr("Mettez Beheread à jour pour lire sur ce serveur (version {version} "
                             "demandée, vous avez la {current}).",
                             version=minimum, current=__version__))


def parse_invitation(text):
    """(adresse du serveur ou None, code) d'un lien d'invitation
    (https://serveur/i/K7M2QX9P) ou d'un code seul (« K7M2 QX9P »)."""
    text = (text or "").strip()
    match = re.match(r"^(https?://[^/\s]+)(?:/.*)?/i/([A-Za-z0-9 -]+)/?$", text)
    if match:
        return match.group(1), re.sub(r"[^A-Za-z0-9]", "", match.group(2)).upper()
    return None, re.sub(r"[^A-Za-z0-9]", "", text).upper()


def preview_invitation(url, code) -> dict:
    """Essai d'une invitation sans la consommer (version requise, profil),
    au format de Client.check. Leve ServerError."""
    http = _Http(url)
    require_version((http.json("/api/v1/version") or {}).get("desktop_min"))
    try:
        info = http.json(f"/api/v1/invitations/{_q(code)}") or {}
    except ServerError as e:
        if e.status == 404:
            raise ServerError(tr("Ce code n'est pas valable (ou a expiré)."), 404) from e
        raise
    return {"version": tr("Invitation de {admin} pour le profil {name}",
                          admin=info.get("admin") or "?", name=info.get("profile") or "?"),
            "count": None}


def enroll(url, code, device_name) -> tuple:
    """Lie cet ordinateur a un profil du serveur : (jeton, profil). Leve
    ServerError (code refuse, serveur injoignable, version trop ancienne)."""
    http = _Http(url)
    require_version((http.json("/api/v1/version") or {}).get("desktop_min"))
    try:
        me = http.json("/api/v1/enroll", method="POST",
                       body={"code": code, "name": device_name, "kind": "desktop"}) or {}
    except ServerError as e:
        if e.status in (401, 403):
            raise ServerError(tr("Ce code n'est pas valable (ou a expiré)."), e.status) from e
        if e.status == 429:
            raise ServerError(tr("Trop de tentatives : réessayez dans quelques minutes."),
                              e.status) from e
        raise
    token = me.get("token")
    if not isinstance(token, str) or not token:
        raise ServerError(tr("Réponse inattendue du serveur : est-ce bien un serveur "
                             "de ce type ?"))
    return token, me.get("profile") or {}


def make_client(config: ServerConfig, secret: str) -> Client:
    return {"beheread": BeheReadClient, "komga": KomgaClient, "kavita": KavitaClient,
            "opds": OpdsClient}[config.kind](config, secret)


# ---------------------------------------------------------------- archive distante

class RemoteArchive:
    """Tome d'un serveur, avec l'interface d'Archive (voir le module)."""

    def __init__(self, book: RemoteBook, client: Client, data: Optional[bytes] = None):
        self.path = book.path
        self.book, self.client = book, client
        self.closed = False
        self._zip = None
        if data is not None:   # fichier complet, deja charge en memoire
            try:
                self._zip = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile as e:
                raise ArchiveError(tr("Archive ZIP invalide :") + f"\n{book.title}\n{e}") from e
            names = [n for n in self._zip.namelist()
                     if Path(n).suffix.lower() in IMAGE_EXTS and "__MACOSX" not in n
                     and not Path(n).name.startswith(".")]
            self.pages = _without_extras(sorted(names, key=_natural_key))
        else:
            self.pages = [f"page {i + 1}" for i in range(book.pages)]
        if not self.pages:
            raise ArchiveError(tr("Aucune page dans ce tome du serveur."))
        self._lock = threading.Lock()

    def __len__(self):
        return len(self.pages)

    def read_page(self, index: int) -> bytes:
        if self.closed:
            raise ArchiveClosedError(self.path)
        if self._zip is not None:
            with self._lock:
                info = self._zip.getinfo(self.pages[index])
                if info.file_size > MAX_PAGE_BYTES:
                    raise ArchiveError(tr("Entrée anormalement volumineuse ignorée ({size} "
                                          "octets) :\n{name}\ndans {path}",
                                          size=info.file_size, name=info.filename,
                                          path=self.book.title))
                return self._zip.read(info)
        try:
            return self.client.page(self.book, index)
        except ServerError as e:
            raise ArchiveError(str(e)) from e

    def read_first_page(self) -> bytes:
        return self.read_page(0)

    def read_image(self, index: int, max_height: int = 0):
        """Comme Archive.read_image ; la couverture d'une vignette vient de
        la vignette du serveur quand il en fournit une (bien plus legere
        que la page entiere)."""
        if index == 0 and 0 < max_height <= COVER_MAX_HEIGHT and self._zip is None:
            try:
                data = self.client.cover(self.book)
            except ServerError:
                data = None
            if data:
                from PySide6.QtCore import QByteArray
                from PySide6.QtGui import QImage
                image = QImage.fromData(QByteArray(data))
                if not image.isNull():
                    if image.height() > max_height:
                        from PySide6.QtCore import Qt
                        image = image.scaledToHeight(max_height, Qt.SmoothTransformation)
                    return image
        return Archive.read_image(self, index, max_height)

    def read_comicinfo(self):
        return None

    def prepare_reading(self):
        pass

    def close(self):
        self.closed = True
        if self._zip is not None:
            with self._lock:
                self._zip.close()


class Registry:
    """Clients des serveurs actifs et tomes connus, pour toute l'application
    (Archive, vignettes, lecteur). Thread-safe."""

    FILES_KEPT = 2   # fichiers complets (OPDS sans PSE) gardes en memoire

    def __init__(self):
        self._lock = threading.Lock()
        self._clients = {}
        self._books = {}
        self._files = OrderedDict()

    def set_clients(self, clients: dict):
        with self._lock:
            self._clients = dict(clients)
            self._files.clear()

    def client(self, server_id) -> Optional[Client]:
        with self._lock:
            return self._clients.get(server_id)

    def add_books(self, books):
        with self._lock:
            for book in books:
                self._books[book.path] = book

    def book(self, path) -> Optional[RemoteBook]:
        with self._lock:
            return self._books.get(path)

    def _parts(self, path):
        with self._lock:
            book = self._books.get(path)
            client = self._clients.get(book.server_id) if book is not None else None
            data = self._files.get(path)
        if book is None or client is None:
            raise ArchiveError(tr("Ce tome n'est plus disponible : son serveur est désactivé "
                                  "ou n'a pas encore été consulté."))
        return book, client, data

    def needs_download(self, path) -> bool:
        """Tome a charger en entier avant de l'ouvrir (OPDS sans PSE)."""
        book = self.book(path)
        if book is None or book.stream or book.pages:
            return False
        if getattr(self.client(book.server_id), "streams", False):
            return False   # serveur Beheread : nombre de pages demande a l'ouverture
        with self._lock:
            return path not in self._files

    def download(self, path):
        """Charge le fichier complet en memoire (thread de travail)."""
        book, client, data = self._parts(path)
        if data is not None:
            return
        try:
            data = client.file(book)
        except ServerError as e:
            raise ArchiveError(str(e)) from e
        with self._lock:
            self._files[path] = data
            self._files.move_to_end(path)
            while len(self._files) > self.FILES_KEPT:
                self._files.popitem(last=False)

    def open(self, path) -> RemoteArchive:
        book, client, data = self._parts(path)
        if not book.pages and getattr(client, "streams", False):
            try:
                book.pages = client.page_count(book)
            except ServerError as e:
                raise ArchiveError(str(e)) from e
        if not book.stream and not book.pages and data is None:
            if self.needs_download(path):
                self.download(path)   # hors du thread UI (voir needs_download)
                book, client, data = self._parts(path)
        return RemoteArchive(book, client, data)


registry = Registry()
