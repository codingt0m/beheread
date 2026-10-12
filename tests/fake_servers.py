"""Faux serveurs de lecture (Komga, Kavita, OPDS) sur 127.0.0.1, pour les
tests : reponses au format documente de chaque serveur, requetes recues
enregistrees. Aucun acces au reseau exterieur."""

import base64
import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage

API_KEY = "cle-kavita"
KOMGA_USER, KOMGA_PASSWORD = "tom", "secret"


def jpeg(color="#8e3b46", w=60, h=90) -> bytes:
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPEG")
    return bytes(data)


def cbz(pages=3) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for k in range(pages):
            z.writestr(f"{k:03}.jpg", jpeg())
    return out.getvalue()


def komga_book(i, series="Berserk", number=None, page=None, completed=False):
    number = i if number is None else number
    return {"id": f"B{i}", "seriesTitle": series, "name": f"{series} {number}",
            "number": number,
            "metadata": {"title": f"{series} - Tome {number}", "numberSort": number,
                         "releaseDate": "1990-05-12",
                         "authors": [{"name": "Kentaro Miura", "role": "writer"},
                                     {"name": "Studio Gaga", "role": "colorist"}]},
            "media": {"pagesCount": 4, "status": "READY"},
            "readProgress": ({"page": page, "completed": completed} if page else None)}


ATOM = ('<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:pse="http://vaemendis.net/opds-pse/ns" '
        'xmlns:dcterms="http://purl.org/dc/terms/"><title>{title}</title>{links}{entries}</feed>')
NAV = ('<entry><title>{title}</title><id>{id}</id>'
       '<link rel="subsection" type="application/atom+xml;profile=opds-catalog;kind=navigation" '
       'href="{href}"/></entry>')


def opds_book(book_id, title, stream=None, count=4, last=0, download=None, cover=None):
    links = ""
    if stream:
        links += (f'<link rel="http://vaemendis.net/opds-pse/stream" type="image/jpeg" '
                  f'href="{stream}" pse:count="{count}" pse:lastRead="{last}"/>')
    if download:
        links += (f'<link rel="http://opds-spec.org/acquisition" type="application/x-cbz" '
                  f'href="{download}"/>')
    if cover:
        links += f'<link rel="http://opds-spec.org/image/thumbnail" type="image/jpeg" href="{cover}"/>'
    return (f"<entry><title>{title}</title><id>{book_id}</id>"
            f"<author><name>Naoki Urasawa</name></author>"
            f"<dcterms:issued>2003-09-01</dcterms:issued>{links}</entry>")


class FakeServers:
    """Etat partage des faux serveurs ; `requests` : (methode, chemin, corps)."""

    def __init__(self):
        self.requests = []
        self.komga_books = [komga_book(i) for i in range(1, 4)] + [
            komga_book(9, series="Pluto", page=3)]
        self.redirect_to = None
        server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server = server
        self.url = f"http://127.0.0.1:{server.server_address[1]}"
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def bodies(self, method, prefix):
        return [body for m, path, body in self.requests if m == method and path.startswith(prefix)]

    def _handler(self):
        state = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _send(self, code, body=b"", kind="application/json", headers=None):
                if isinstance(body, (dict, list)):
                    body = json.dumps(body).encode()
                elif isinstance(body, str):
                    body = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                return json.loads(raw) if raw else None

            def do_GET(self):
                state.requests.append(("GET", self.path, None))
                self._route("GET")

            def do_POST(self):
                state.requests.append(("POST", self.path, self._body()))
                self._route("POST")

            def do_PATCH(self):
                state.requests.append(("PATCH", self.path, self._body()))
                self._route("PATCH")

            def _komga_auth(self):
                basic = "Basic " + base64.b64encode(
                    f"{KOMGA_USER}:{KOMGA_PASSWORD}".encode()).decode()
                return self.headers.get("Authorization") == basic or \
                    self.headers.get("X-API-Key") == "komga-key"

            def _route(self, method):
                url = urlsplit(self.path)
                path, query = url.path, parse_qs(url.query)
                if path == "/redirect":
                    return self._send(302, headers={"Location": state.redirect_to})
                if path.startswith("/api/v1/"):
                    if not self._komga_auth():
                        return self._send(401, {"error": "Unauthorized"})
                    return self._komga(method, path, query)
                if path.startswith("/api/opds/"):
                    return self._kavita_opds(path)
                if path.startswith("/api/Plugin/authenticate"):
                    if query.get("apiKey") != [API_KEY]:
                        return self._send(401, "")
                    return self._send(200, {"token": "jwt-123", "username": "tom"})
                if path == "/api/Reader/progress":
                    ok = self.headers.get("Authorization") == "Bearer jwt-123"
                    return self._send(200 if ok else 401, b"")
                if path.startswith("/opds"):
                    return self._opds(path, query)
                if path.startswith("/img/") or path.startswith("/thumb/"):
                    return self._send(200, jpeg(), "image/jpeg")
                if path.startswith("/file/"):
                    return self._send(200, cbz(), "application/x-cbz")
                return self._send(404, "")

            def _komga(self, method, path, query):
                if path == "/api/v1/users/me":
                    return self._send(200, {"email": "tom@example.org"})
                if path == "/api/v1/actuator/info":
                    return self._send(200, {"build": {"version": "1.21.2"}})
                if path == "/api/v1/books":
                    size, page = int(query["size"][0]), int(query.get("page", ["0"])[0])
                    books = state.komga_books
                    if size == 1:
                        return self._send(200, {"content": books[:1], "totalElements": len(books),
                                                "last": False})
                    size = 2   # pages de deux tomes : la pagination est exercee
                    chunk = books[page * size:(page + 1) * size]
                    return self._send(200, {"content": chunk, "totalElements": len(books),
                                            "last": (page + 1) * size >= len(books)})
                parts = path.split("/")
                if method == "PATCH" and path.endswith("/read-progress"):
                    return self._send(204, b"")
                if "pages" in parts or path.endswith("/thumbnail"):
                    return self._send(200, jpeg(), "image/jpeg")
                return self._send(404, "")

            def _opds(self, path, query):
                links = ""
                if path == "/opds":
                    entries = (NAV.format(title="Nouveautés", id="n", href="/opds/latest")
                               + NAV.format(title="Séries", id="s", href="/opds/series")
                               + NAV.format(title="Ailleurs", id="x",
                                            href="http://example.invalid/opds/evil"))
                    title = "Ma bibliothèque"
                elif path == "/opds/series":
                    entries = NAV.format(title="Monster", id="m", href="/opds/monster")
                    title = "Séries"
                elif path == "/opds/latest":
                    entries = "".join(opds_book(f"urn:x:{i}", f"Livre {i}", stream=f"/img/{i}/{{pageNumber}}")
                                      for i in range(5, 9))
                    entries += opds_book("urn:monster:1", "Volume 1",
                                         stream="/img/m1/{pageNumber}?w={maxWidth}")
                    title = "Nouveautés"
                    if not query.get("p"):
                        links = '<link rel="next" type="application/atom+xml" href="/opds/latest?p=2"/>'
                    else:
                        entries = opds_book("urn:x:99", "Pluto - Tome 2", download="/file/99",
                                            cover="/thumb/99")
                elif path == "/opds/monster":
                    entries = (opds_book("urn:monster:1", "Volume 1",
                                         stream="/img/m1/{pageNumber}?w={maxWidth}", last=2)
                               + opds_book("urn:monster:2", "Volume 2",
                                           stream="/img/m2/{pageNumber}", last=4))
                    title = "Monster"
                else:
                    return self._send(404, "")
                feed = ATOM.format(title=title, links=links, entries=entries)
                return self._send(200, feed, "application/atom+xml")

            def _kavita_opds(self, path):
                prefix = f"/api/opds/{API_KEY}"
                if not path.startswith(prefix):
                    return self._send(401, "")
                rest = path[len(prefix):]
                if rest in ("", "/"):
                    entries = NAV.format(title="Berserk", id="k1", href=f"{prefix}/series/1")
                    title = "Kavita"
                elif rest == "/series/1":
                    stream = (f"{prefix}/image?libraryId=1&amp;seriesId=1&amp;volumeId=7&amp;"
                              "chapterId=12&amp;pageNumber={pageNumber}")
                    entries = opds_book("kavita-chapter-12", "Volume 1", stream=stream, count=5, last=2)
                    title = "Berserk"
                elif rest.startswith("/image"):
                    return self._send(200, jpeg(), "image/jpeg")
                else:
                    return self._send(404, "")
                return self._send(200, ATOM.format(title=title, links="", entries=entries),
                                  "application/atom+xml")

        return Handler
