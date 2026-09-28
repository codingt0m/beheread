"""Connexion a AniList sans copier-coller : apres l'autorisation, AniList
renvoie le navigateur vers http://127.0.0.1:<port>/anilist#access_token=...
(voir beheread/config.py). Le jeton est dans le FRAGMENT de l'adresse, que le
navigateur n'envoie jamais a un serveur : la page servie ici le lit en
JavaScript et le remet a Beheread par une requete POST locale.

Precautions :
* ecoute uniquement sur 127.0.0.1 (invisible depuis le reseau), et seulement
  le temps de la connexion ;
* le POST n'est accepte que s'il vient de cette page elle-meme (en-tete
  Origin), pour qu'un autre site ouvert dans le navigateur ne puisse pas
  injecter un jeton ;
* le jeton recu est ensuite verifie aupres d'AniList (compte associe) avant
  d'etre enregistre (voir ui/library/dialogs.AniListLoginDialog).
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QObject, Signal

MAX_BODY = 16 * 1024

_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Beheread · AniList</title>
<style>
 body { font-family: system-ui, "Segoe UI", sans-serif; background: #1b1e24; color: #d7dbe2;
        display: grid; place-items: center; min-height: 90vh; margin: 0; }
 main { max-width: 32rem; padding: 2rem; text-align: center; }
 h1 { font-size: 1.3rem; } p { color: #8b93a1; }
</style></head>
<body><main><h1 id="t">Connexion à AniList…</h1><p id="m"></p></main>
<script>
(function () {
  var p = new URLSearchParams(location.hash.slice(1) || location.search.slice(1));
  var t = document.getElementById("t"), m = document.getElementById("m");
  var token = p.get("access_token");
  var body = token ? {token: token} : {error: p.get("error_description") || p.get("error") || "annule"};
  history.replaceState(null, "", location.pathname);   // retire le jeton de l'adresse
  fetch("/anilist/done", {method: "POST", headers: {"Content-Type": "application/json"},
                          body: JSON.stringify(body)})
    .then(function () {
      t.textContent = token ? "Beheread est connecté à AniList" : "Connexion annulée";
      m.textContent = "Vous pouvez fermer cet onglet et revenir à Beheread.";
    })
    .catch(function () {
      t.textContent = "Beheread ne répond plus";
      m.textContent = "Relancez la connexion depuis les préférences de Beheread.";
    });
})();
</script></body></html>
"""


class LocalAuthReceiver(QObject):
    """Serveur HTTP local ephemere. Emet tokenReceived(jeton) ou failed(message)."""

    tokenReceived = Signal(str)
    failed = Signal(str)

    def __init__(self, port: int, path: str, parent=None):
        super().__init__(parent)
        self.port = port
        self.path = path
        self._server = None
        self._thread = None
        self._done = False

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        """Demarre l'ecoute. Leve OSError si le port est deja pris."""
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):   # pas de jeton dans le journal
                logging.debug("auth locale : %s", self.command)

            def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.split("?")[0] == receiver.path:
                    self._send(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
                else:
                    self._send(404)

            def do_POST(self):
                # le corps est toujours lu (borne) avant de repondre : sinon,
                # sous Windows, repondre sans l'avoir lu peut reinitialiser la
                # connexion et le client ne voit jamais la reponse
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = -1
                if length <= 0 or length > MAX_BODY:
                    self._send(400)
                    return
                raw = self.rfile.read(length)
                if self.path != receiver.path + "/done":
                    self._send(404)
                    return
                if self.headers.get("Origin") != receiver.origin:
                    self._send(403)   # requete venue d'un autre site
                    return
                try:
                    data = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self._send(400)
                    return
                self._send(204)
                receiver._deliver(data if isinstance(data, dict) else {})

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="beheread-anilist-auth", daemon=True)
        self._thread.start()

    def _deliver(self, data):
        if self._done:
            return
        self._done = True
        token = data.get("token")
        if isinstance(token, str) and token.strip():
            self.tokenReceived.emit(token.strip())
        else:
            self.failed.emit(str(data.get("error") or "Connexion annulée."))

    def stop(self):
        server, self._server = self._server, None
        if server is not None:
            threading.Thread(target=lambda: (server.shutdown(), server.server_close()),
                             daemon=True).start()
