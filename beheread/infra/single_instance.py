"""Instance unique de l'application.

Sans elle, double-cliquer un second fichier dans l'explorateur lancait un
second processus : les deux gardaient progress.json en memoire et le
reecrivaient en entier, le dernier ecrivain effacant la progression de
l'autre. Desormais :

* la premiere instance prend un verrou (QLockFile, dans le dossier de
  donnees) et ouvre un canal local (QLocalServer) ;
* une instance suivante ne prend pas le verrou : elle transmet sa demande
  (ouvrir tel fichier, ou simplement « se montrer ») a la premiere par ce
  canal, puis se termine sans jamais charger les donnees.

Le verrou, et non `QLocalServer.listen`, decide qui est l'instance principale :
sous Windows, deux serveurs peuvent ecouter sur le meme nom de pipe. Un
verrou laisse par un processus plante est detecte (PID mort) et repris.
"""

import getpass
import hashlib
import json
import logging
import sys
import time

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

CONNECT_TIMEOUT_MS = 500
CONNECT_ATTEMPTS = 6        # ~3 s : l'instance principale peut etre en plein demarrage
ACK_TIMEOUT_MS = 3000
ACK = b"ok\n"              # accuse de reception renvoye par l'instance principale


def default_server_name() -> str:
    """Nom du canal, propre a l'utilisateur Windows (deux sessions sur la
    meme machine ne doivent pas se parler)."""
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    digest = hashlib.sha1(user.encode("utf-8", "replace")).hexdigest()[:12]
    return f"beheread-{digest}"


def encode(message: dict) -> bytes:
    return json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"


def decode(data: bytes):
    """Message decode, ou None s'il est illisible (le canal est local, mais
    rien n'empeche un autre programme de s'y connecter : on valide)."""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(msg, dict):
        return None
    path = msg.get("open")
    if path is not None and not isinstance(path, str):
        return None
    return msg


def _allow_foreground():
    """Windows n'autorise un processus a passer au premier plan que si le
    processus actif le lui permet. L'instance secondaire (celle que
    l'utilisateur vient de lancer) cede donc ce droit a l'instance principale,
    sans quoi celle-ci ne ferait que clignoter dans la barre des taches."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(0xFFFFFFFF)   # ASFW_ANY
    except Exception:
        logging.debug("AllowSetForegroundWindow en echec", exc_info=True)


def send_to_primary(message: dict, name: str = None) -> bool:
    """Transmet `message` a l'instance principale. True seulement si celle-ci
    en a accuse reception : sans accuse, l'appelant se lance normalement
    plutot que de disparaitre sans rien ouvrir.

    (waitForBytesWritten ne suffit pas comme preuve : sous Windows, une
    ecriture dans le pipe peut se terminer immediatement, et la fonction
    repond alors False alors que le message est bien parti.)"""
    name = name or default_server_name()
    _allow_foreground()
    for _attempt in range(CONNECT_ATTEMPTS):
        sock = QLocalSocket()
        sock.connectToServer(name)
        if not sock.waitForConnected(CONNECT_TIMEOUT_MS):
            time.sleep(0.25)
            continue
        sock.write(encode(message))
        sock.flush()
        reply = bytearray()
        deadline = time.monotonic() + ACK_TIMEOUT_MS / 1000
        while ACK not in reply and time.monotonic() < deadline:
            if sock.bytesAvailable() or sock.waitForReadyRead(100):
                reply.extend(bytes(sock.readAll()))
            elif sock.state() == QLocalSocket.UnconnectedState:
                break   # connexion fermee sans accuse
        sock.abort()
        return ACK in reply
    return False


class SingleInstance(QObject):
    """Verrou + canal de l'instance principale. `messageReceived` porte les
    demandes des instances lancees ensuite ({"open": chemin} ou
    {"activate": True})."""

    messageReceived = Signal(dict)

    def __init__(self, lock_path, name: str = None, parent=None):
        super().__init__(parent)
        self.name = name or default_server_name()
        self._lock = QLockFile(str(lock_path))
        # 0 : un verrou n'est jamais perime par son age (l'application reste
        # ouverte des heures), seulement si son processus n'existe plus
        self._lock.setStaleLockTime(0)
        self._server = None
        self._buffers = {}

    def acquire(self) -> bool:
        """True si ce processus devient l'instance principale."""
        if not self._lock.tryLock(0):
            return False
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        QLocalServer.removeServer(self.name)   # socket orphelin d'un plantage (hors Windows)
        if not self._server.listen(self.name):
            logging.warning("Canal d'instance unique indisponible : %s",
                            self._server.errorString())
        self._server.newConnection.connect(self._on_new_connection)
        return True

    def release(self):
        if self._server is not None:
            self._server.close()
        self._lock.unlock()

    def _on_new_connection(self):
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            self._buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self._on_ready(s))
            sock.disconnected.connect(lambda s=sock: self._on_disconnected(s))
            self._on_ready(sock)   # donnees peut-etre deja arrivees

    def _on_ready(self, sock):
        buf = self._buffers.get(sock)
        if buf is None:
            return
        buf.extend(bytes(sock.readAll()))
        if b"\n" not in buf:
            if len(buf) > 64 * 1024:   # message anormal : on coupe
                self._drop(sock)
            return
        line = bytes(buf).split(b"\n", 1)[0]
        msg = decode(line)
        if msg is None:
            self._drop(sock)
            logging.warning("Message d'instance illisible ignore")
            return
        sock.write(ACK)          # accuse reception avant de traiter la demande
        sock.flush()
        self._drop(sock)
        self.messageReceived.emit(msg)

    def _on_disconnected(self, sock):
        self._on_ready(sock)   # dernier morceau eventuel
        self._drop(sock)

    def _drop(self, sock):
        if self._buffers.pop(sock, None) is not None:
            sock.disconnectFromServer()
            sock.deleteLater()
